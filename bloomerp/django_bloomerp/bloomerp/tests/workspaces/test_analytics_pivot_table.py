"""Exercise SQL pivot rendering outside model lifecycle and request scenarios."""
from typing import Any
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.http import HttpRequest
from django.test import RequestFactory

from bloomerp.dataviews.pivot_table.renderer import MAX_PIVOT_LEAF_COLUMNS, PivotTableResult, PivotTableTooWide
from bloomerp.services.sql_services import SqlExecutor, SqlQueryResponse
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileType, get_field_options_form_factory
from bloomerp.workspaces.analytics_tile.pivot_table import AnalyticsPivotTable, AnalyticsPivotTableRenderer, PivotTableTooTall
from bloomerp.workspaces.analytics_tile.sql_utils import quote_identifier


class TestAnalyticsPivotTable(BaseBloomerpTestCaseWithModels):
    """Use real authorized SQL execution to test aggregation, limits, and rendered markup."""

    auto_create_customers = False

    def config(self, **overrides: Any) -> AnalyticsTileConfig:
        """Build a pivot over the base case's customer model with independent measures."""
        table = quote_identifier(self.CustomerModel._meta.db_table)
        values: dict[str, Any] = {
            "type": "PIVOT_TABLE",
            "query": f"SELECT first_name AS region, last_name AS team, age AS amount FROM {table}",
            "fields": {
                "rows": [{"name": "region"}, {"name": "team"}],
                "columns": [{"name": "team"}],
                "values": [{"name": "amount", "opts": {"aggregator": "avg"}}],
            },
        }
        values.update(overrides)
        return AnalyticsTileConfig(**values)

    def build(self, config: AnalyticsTileConfig, page: int = 1, page_size: int = 25) -> tuple[PivotTableResult, SqlQueryResponse]:
        """Build the shared template contract from real SQL aggregate queries."""
        pivot = AnalyticsPivotTable(config, config.query, SqlExecutor(self.admin_user))
        pagination = pivot.prepare(page, page_size)
        return pivot.build(), pagination

    def request(self, **params: Any) -> HttpRequest:
        """Provide the authenticated tile request with framework query parameters."""
        request = RequestFactory().get("/components/render-layout-item/", params)
        request.user = self.admin_user
        return request

    def test_hierarchy_and_weighted_totals(self) -> None:
        """Use case: Unequal group sizes are averaged across nested pivot rows.
        Expected result: Parent and grand totals aggregate original records, not displayed averages.
        """
        # 1. Create unequal groups and two independently aggregated measures.
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="North", last_name="Alpha", age=10),
            self.CustomerModel(first_name="North", last_name="Alpha", age=30),
            self.CustomerModel(first_name="North", last_name="Beta", age=80),
            self.CustomerModel(first_name="South", last_name="Gamma", age=0),
        ])
        config = self.config()
        config.fields["values"].append(config.fields["values"][0].model_copy(update={"opts": {"aggregator": "sum"}}))
        # 2. Check the shared row hierarchy, independent aggregations, and true averages.
        result, pagination = self.build(config)
        self.assertEqual(pagination.row_count, 2)
        north = result.rows[0]
        self.assertEqual(north.label, "North")
        self.assertEqual(north.totals, [40, 120])
        self.assertTrue(north.has_children)
        self.assertEqual(result.rows[1].parent_id, north.row_id)
        self.assertEqual(result.grand_totals, [30, 120])
        self.assertEqual(result.header_rows[0][0].colspan, 2)
        self.assertEqual(result.effective_aggregations, ["avg", "sum"])

    def test_pagination_keeps_whole_groups_and_query_parameters(self) -> None:
        """Use case: A pivot has more top-level groups than fit on its first page.
        Expected result: Pages retain whole groups and pagination links preserve framework state.
        """
        # 1. Create 11 roots, each with two children.
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name=f"Group {index:02}", last_name=team, age=5)
            for index in range(11) for team in ("A", "B")
        ])
        config = self.config(opts={"page_size": "10"})
        # 2. Verify the second page contains its complete hierarchy and page-scoped totals.
        result, page = self.build(config, page=2, page_size=10)
        self.assertEqual(page.total_pages, 2)
        self.assertEqual([row.label for row in result.rows], ["Group 10", "A", "B"])
        self.assertEqual(result.grand_totals, [5])
        # 3. Verify tile rendering reuses the registered pivot component and scoped HTMX target.
        html = AnalyticsPivotTableRenderer.render(config, self.request(page=2, tile_id="pivot-a", colspan=2))
        markup = BeautifulSoup(html, "html.parser")
        self.assertIsNotNone(markup.select_one('[bloomerp-component="pivot-table"]'))
        previous = markup.select_one('button[hx-get]')
        self.assertIn("tile_id=pivot-a", previous["hx-get"])
        self.assertIn("colspan=2", previous["hx-get"])
        self.assertIn("page=1", previous["hx-get"])
        self.assertEqual(markup.select_one("nav")["hx-target"], "closest [data-layout-item-body]")

    def test_width_limit_and_draft_feedback(self) -> None:
        """Use case: An analytics pivot exceeds the dataview column limit or lacks required slots.
        Expected result: It renders the shared width warning or a helpful draft prompt.
        """
        # 1. Create one more distinct column than the shared limit.
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="North", last_name=f"Column {index}", age=1)
            for index in range(MAX_PIVOT_LEAF_COLUMNS + 1)
        ])
        config = self.config()
        # 2. Check the builder rejects excessive width and the renderer handles it.
        with self.assertRaises(PivotTableTooWide):
            self.build(config)
        html = AnalyticsPivotTableRenderer.render(config, self.request())
        self.assertIn("too many columns", html)
        self.assertNotIn('<table', html)
        # 3. Check incomplete editor states remain renderable without querying.
        draft = self.config(fields={"rows": [{"name": "region"}]})
        with self.assertNumQueries(0):
            self.assertIn("Select at least one row field", AnalyticsPivotTableRenderer.render(draft, self.request()))

    def test_empty_data_null_groups_and_text_fallback(self) -> None:
        """Use case: A pivot has empty data, null dimensions, or a numeric aggregation on text.
        Expected result: Empty output is safe, null groups survive paging, and text uses count.
        """
        # 1. Check an empty data source.
        result, _page = self.build(self.config())
        self.assertEqual(result.rows, [])
        # 2. Aggregate text under a null root, using the dataview's count fallback.
        self.CustomerModel.objects.create(first_name="North", last_name="Alpha", age=10)
        table = quote_identifier(self.CustomerModel._meta.db_table)
        config = self.config(query=f"SELECT NULL AS region, last_name AS team FROM {table}", fields={
            "rows": [{"name": "region"}], "values": [{"name": "team", "opts": {"aggregator": "sum"}}],
        })
        result, _page = self.build(config)
        self.assertEqual(result.rows[0].label, "Unassigned")
        self.assertEqual(result.rows[0].cells, [1])
        self.assertEqual(result.effective_aggregations, ["count"])

    def test_editor_aggregation_choices(self) -> None:
        """Use case: The analytics editor configures value fields of different types.
        Expected result: It offers the pivot dataview's numeric, boolean, and text operations.
        """
        # 1. Resolve the registered pivot value slot.
        definition = AnalyticsTileType.PIVOT_TABLE.value
        values = next(field for field in definition.fields if field.key == "values")
        # 2. Verify type-aware forms accept only supported aggregation methods.
        for field_type, expected in (
            ("numeric", {"count", "sum", "min", "max", "avg"}),
            ("bool", {"count", "sum"}),
            ("text", {"count"}),
        ):
            with self.subTest(field_type=field_type):
                form = get_field_options_form_factory(values, field_type)()
                self.assertEqual({value for value, _label in form.fields["aggregator"].choices}, expected)

    def test_quoted_aliases_and_null_first_measure(self) -> None:
        """Use case: Query aliases contain quotes or collide with internal aggregation names.
        Expected result: Quoted dimensions and a null-first numeric measure aggregate correctly.
        """
        # 1. Use a read-only query with unusual but valid output names and a null first value.
        config = self.config(query='SELECT \'North\' AS "pivot_value_0", NULL AS "a""mount" UNION ALL SELECT \'North\', 12', fields={
            "rows": [{"name": "pivot_value_0"}],
            "values": [{"name": 'a"mount', "opts": {"aggregator": "sum"}}],
        })
        # 2. Verify metadata inference and aggregate aliases preserve both the label and value.
        result, _page = self.build(config)
        self.assertEqual(result.rows[0].label, "North")
        self.assertEqual(result.rows[0].cells, [12])
        self.assertEqual(result.effective_aggregations, ["sum"])

    def test_pivot_respects_framework_row_and_field_policies(self) -> None:
        """Use case: A user may see one region but cannot read its measure field.
        Expected result: SQL pivots retain row scoping and never expose the denied measure.
        """
        from bloomerp.filters.definition import FilterCondition
        from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
        from bloomerp.permissions.manager import PolicyManager

        # 1. Grant one region and only the dimension fields through the framework policy manager.
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="Visible", last_name="A", age=123),
            self.CustomerModel(first_name="Hidden", last_name="B", age=999),
        ])
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={name: [BloomerpPermission.VIEW] for name in ("first_name", "last_name")},
            row_permissions=[RowPolicyRuleContent(
                connector="AND", permissions=[BloomerpPermission.VIEW],
                conditions=[FilterCondition(field_path="first_name", lookup_id="equals", value="Visible")],
            )],
        )
        PolicyManager.assign(policy, self.normal_user)
        config = self.config()
        # 2. Run every pivot query through the same authenticated SQL executor.
        pivot = AnalyticsPivotTable(config, config.query, SqlExecutor(self.normal_user))
        pagination = pivot.prepare(1, 25)
        result = pivot.build()
        self.assertEqual(pagination.row_count, 1)
        self.assertEqual([row.label for row in result.rows], ["Visible", "A"])
        self.assertNotIn(123, result.rows[0].cells)
        self.assertNotIn(999, result.grand_totals)

    def test_database_returns_only_grouped_aggregates(self) -> None:
        """Use case: Many source records contribute to a small pivot.
        Expected result: SQL returns bounded grouped aggregates, never raw source records.
        """
        # 1. Create 200 records that must collapse to one row with two value columns.
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="North", last_name=team, age=amount)
            for _index in range(100) for team, amount in (("A", 1), ("B", 2))
        ])
        config = self.config(fields={
            "rows": [{"name": "region"}], "columns": [{"name": "team"}],
            "values": [{"name": "amount", "opts": {"aggregator": "sum"}}],
        })
        executor = SqlExecutor(self.admin_user)
        execute = executor.execute_query
        responses: list[SqlQueryResponse] = []

        def record_query(query: str, page: int = 1, page_size: int = 25, paginate: bool = True) -> SqlQueryResponse:
            """Observe the actual database result sizes before the renderer sees them."""
            response = execute(query, page=page, page_size=page_size, paginate=paginate)
            responses.append(response)
            return response

        # 2. Build the pivot while recording the real database response boundary.
        with patch.object(executor, "execute_query", side_effect=record_query):
            pivot = AnalyticsPivotTable(config, config.query, executor)
            pivot.prepare(1, 25)
            result = pivot.build()
        # 3. Source rows collapse to two aggregate records, with totals computed separately.
        aggregate_responses = [response for response in responses if pivot.value_aliases[0] in response.columns]
        grouped = next(response for response in aggregate_responses if "region" in response.columns and "team" in response.columns)
        self.assertEqual([record[pivot.value_aliases[0]] for record in grouped.rows], [100, 200])
        self.assertEqual(len(grouped.rows), 2)
        self.assertLessEqual(max(len(response.rows) for response in responses), 2)
        self.assertEqual(result.rows[0].cells, [100, 200])
        self.assertEqual(result.grand_totals, [300])

    def test_nested_row_fetch_is_bounded_before_materialization(self) -> None:
        """Use case: A single top-level group contains too many nested rows.
        Expected result: SQL LIMIT detects overflow within the budget and the tile shows safe feedback.
        """
        # 1. Create more descendants than a deliberately small test rendering budget.
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="North", last_name=f"Team {index:02}", age=1)
            for index in range(15)
        ])
        config = self.config(fields={
            "rows": [{"name": "region"}, {"name": "team"}],
            "values": [{"name": "amount", "opts": {"aggregator": "sum"}}],
        })
        executor = SqlExecutor(self.admin_user)
        execute = executor.execute_query
        response_sizes: list[int] = []

        def record_query(query: str, page: int = 1, page_size: int = 25, paginate: bool = True) -> SqlQueryResponse:
            """Measure fetched records rather than just checking a Python-side truncation."""
            response = execute(query, page=page, page_size=page_size, paginate=paginate)
            response_sizes.append(len(response.rows))
            return response

        # 2. One root consumes a row; the next fetch permits three children plus one sentinel.
        with patch("bloomerp.workspaces.analytics_tile.pivot_table.MAX_PIVOT_RENDERED_ROWS", 4):
            with patch.object(executor, "execute_query", side_effect=record_query):
                pivot = AnalyticsPivotTable(config, config.query, executor)
                pivot.prepare(1, 25)
                with self.assertRaises(PivotTableTooTall):
                    pivot.build()
            self.assertEqual(response_sizes[-1], 4)
            self.assertLessEqual(max(response_sizes), 4)
            # 3. Fail visibly instead of silently displaying incomplete groups or totals.
            html = AnalyticsPivotTableRenderer.render(config, self.request())
            self.assertIn("too many nested rows", html)
            self.assertNotIn("<table", html)

    def test_count_distinguishes_null_and_missing_groups(self) -> None:
        """Use case: Some column groups are missing and others have only null measures.
        Expected result: Database pivot cells retain zero counts and blank missing cells separately.
        """
        # 1. Include a null column dimension and a missing combination in a small SQL source.
        config = self.config(query=(
            "SELECT 'A' AS region, NULL AS team, NULL AS amount "
            "UNION ALL SELECT 'A', 'Y', 1 UNION ALL SELECT 'B', NULL, 3 "
            "UNION ALL SELECT 'B', 'Z', 4"
        ), fields={
            "rows": [{"name": "region"}], "columns": [{"name": "team"}],
            "values": [{"name": "amount", "opts": {"aggregator": "count"}}],
        })
        # 2. Locate columns by labels so both SQLite and PostgreSQL null ordering are supported.
        result, _page = self.build(config)
        columns = [header.label for header in result.header_rows[0]]
        cells = dict(zip(columns, result.rows[0].cells))
        self.assertEqual(cells, {"Unassigned": 0, "Y": 1, "Z": None})
        self.assertEqual(result.rows[0].totals, [1])
        self.assertEqual(result.grand_totals, [3])

    def test_page_keys_are_escaped_and_reused(self) -> None:
        """Page filtering preserves quoted values without repeating page discovery in aggregates."""
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="O'Reilly", last_name="A", age=7),
            self.CustomerModel(first_name="Z", last_name="B", age=99),
        ])
        config = self.config()
        executor = SqlExecutor(self.admin_user)
        pivot = AnalyticsPivotTable(config, config.query, executor)
        pivot.prepare(1, 1)
        with patch.object(executor, "execute_query", wraps=executor.execute_query) as execute:
            result = pivot.build()
        self.assertEqual(result.grand_totals, [7])
        self.assertEqual([row.label for row in result.rows], ["O'Reilly", "A"])
        for call in execute.call_args_list:
            query = call.args[0]
            self.assertNotIn("DENSE_RANK", query)
            self.assertNotIn("bloomerp_pivot_page", query)
            self.assertNotIn("JOIN", query)
            self.assertIn("LIMIT", query)

    def test_sparse_aggregate_fetch_is_bounded(self) -> None:
        """Grouped cell overflow is rejected at the SQL boundary rather than truncated silently."""
        self.CustomerModel.objects.bulk_create([
            self.CustomerModel(first_name="North", last_name=team, age=1)
            for team in ("A", "B", "C")
        ])
        config = self.config()
        executor = SqlExecutor(self.admin_user)
        pivot = AnalyticsPivotTable(config, config.query, executor)
        pivot.prepare(1, 25)
        with patch.object(executor, "execute_query", wraps=executor.execute_query) as execute:
            with self.assertRaises(PivotTableTooTall):
                pivot.grouped_rows(config.fields["columns"], 2)
        self.assertTrue(execute.call_args.args[0].endswith("LIMIT 3"))
