"""Analytics queries reuse the canonical filter parser and SQL lookup compiler."""
import json
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.workspaces.analytics_tile.kpi import build_kpi_aggregation_query
from bloomerp.workspaces.analytics_tile.model import (
    AnalyticsTileConfig,
    AnalyticsTileFilter,
    FieldConfig,
    get_filtered_query,
)
from bloomerp.workspaces.analytics_tile.two_dim_chart import build_two_dim_chart_query
from bloomerp.workspaces.analytics_tile.utils import analytics_tile_filter_field_factory
from django.core.exceptions import ValidationError
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase


class TestAnalyticsQueryFilters(SimpleTestCase):
    def config(self, name='week', **kwargs):
        return AnalyticsTileConfig(query='SELECT 1 AS week;', type='TABLE', filters=[
            AnalyticsTileFilter(field=name, type='numeric'),
        ], **kwargs)

    def params(self, *groups):
        return {'filter': json.dumps([group.model_dump() for group in groups])}

    def condition(self, path='week', value='12', lookup='equals'):
        return FilterCondition(field_path=path, lookup_id=lookup, value=value)

    def test_numeric_or_and_groups(self):
        """
        UC: Two numeric alternatives are combined with an upper bound.
        Expected Result: SQL preserves OR within the first group and AND between groups, with cleaned numbers.
        """
        query = get_filtered_query(self.config(), self.params(
            Filter(connector='OR', conditions=[self.condition(value='1'), self.condition(value='2')]),
            Filter(connector='AND', conditions=[self.condition(value='3', lookup='less_than')]),
        ))
        self.assertIn(' OR ', query)
        self.assertIn(' AND ', query)
        self.assertIn('"week" = 1', query)
        self.assertIn('"week" < 3', query)
        self.assertNotIn(';', query)

    def test_invalid_values_and_unknown_json_fields_fail(self):
        """
        UC: A canonical condition contains an invalid number or unconfigured field.
        Expected Result: Validation rejects the condition instead of silently dropping it.
        """
        for condition in [self.condition(value='bad'), self.condition(path='secret'), self.condition(lookup='missing')]:
            with self.subTest(condition=condition), self.assertRaises(ValidationError):
                get_filtered_query(self.config(), self.params(Filter(connector='AND', conditions=[condition])))

    def test_repeated_shorthand_and_json(self):
        """
        UC: Repeated shorthand accompanies a JSON group.
        Expected Result: All conditions are included with implicit AND.
        """
        params = QueryDict('', mutable=True)
        params.setlist('week__gte', ['1', '2'])
        params['filter'] = self.params(Filter(connector='AND', conditions=[self.condition(value='3')]))['filter']
        query = get_filtered_query(self.config(), params)
        self.assertIn('"week" >= 1', query)
        self.assertIn('"week" >= 2', query)
        self.assertIn('"week" = 3', query)

    def test_shared_alias_and_other_tile_projection(self):
        """
        UC: A shared condition maps to differently named columns, alongside a tile-specific condition.
        Expected Result: Each tile uses its own column; unrelated conditions are omitted.
        """
        configs = [self.config(), self.config('reporting_week')]
        configs[1].filters[0].shared_key = 'week'
        tiles = [SimpleNamespace(pk=index, title=str(index), get_config_object=lambda config=config: config,
                 get_tile_type_definition=lambda: SimpleNamespace(filter_fields_factory=analytics_tile_filter_field_factory))
                 for index, config in enumerate(configs, 1)]
        resolver = FilterFieldResolver(workspace=SimpleNamespace(get_tiles=lambda: tiles))
        params = self.params(Filter(connector='OR', conditions=[
            self.condition(path='shared:week'), self.condition(path='tile_1:week', value='99'),
        ]))
        query = get_filtered_query(configs[1], params, resolver=resolver, tile_id='2')
        self.assertIn('"reporting_week" = 12', query)
        self.assertNotIn('99', query)
        self.assertNotIn(' OR ', query)

    def test_explicit_empty_groups(self):
        """
        UC: An explicitly empty AND or OR group is submitted.
        Expected Result: AND compiles to true and OR compiles to false.
        """
        for connector, expected in [('AND', 'TRUE'), ('OR', 'FALSE')]:
            query = get_filtered_query(self.config(), self.params(Filter(connector=connector)))
            self.assertIn(expected, query)

    def test_other_tile_only_does_not_filter(self):
        """
        UC: Every condition applies to another tile.
        Expected Result: The current tile query is not wrapped with a predicate.
        """
        query = get_filtered_query(self.config(), self.params(Filter(connector='OR', conditions=[self.condition(path='tile_2:week')])), tile_id='1')
        self.assertEqual(query, 'SELECT 1 AS week')

    def test_literal_and_identifier_escaping(self):
        """
        UC: A string value contains SQL syntax and the configured column contains a quote.
        Expected Result: The value stays a quoted literal and the column is quoted as an identifier.
        """
        config = AnalyticsTileConfig(query='SELECT 1', type='TABLE', filters=[AnalyticsTileFilter(field='odd"name', type='text')])
        query = get_filtered_query(config, self.params(Filter(connector='AND', conditions=[self.condition(path='odd"name', value="x'; DROP TABLE users; --")])) )
        self.assertIn('"odd""name"', query)
        prefix = "E" if connection.vendor == "postgresql" else ""
        self.assertIn(prefix + "'x''; DROP TABLE users; --'", query)

    def test_compiled_numeric_groups_select_expected_rows(self):
        """
        UC: Execute an OR group combined with an AND bound on numeric results.
        Expected Result: Only rows satisfying the complete grouped predicate are returned.
        """
        import sqlite3
        config = self.config()
        config.query = 'SELECT 1 AS week UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4'
        query = get_filtered_query(config, self.params(
            Filter(connector='OR', conditions=[self.condition(value='1'), self.condition(value='2', lookup='greater_than')]),
            Filter(connector='AND', conditions=[self.condition(value='4', lookup='less_than')]),
        ))
        # Numeric predicates use SQL common to PostgreSQL and SQLite; this
        # isolated execution check does not require the application's database.
        with sqlite3.connect(':memory:') as connection:
            self.assertEqual(connection.execute(query).fetchall(), [(1,), (3,)])




@dataclass
class _AnalyticsFixtureTile:
    """Expose a real analytics config to workspace shared-field discovery."""

    pk: str
    config: AnalyticsTileConfig
    title: str = "Email analysis"

    def get_config_object(self) -> AnalyticsTileConfig:
        """Return the fixture's analytics configuration."""
        return self.config

    def get_tile_type_definition(self) -> SimpleNamespace:
        """Use the production analytics field factory during discovery."""
        return SimpleNamespace(filter_fields_factory=analytics_tile_filter_field_factory)


class TestAnalyticsContainsExecution(BaseBloomerpTestCaseWithModels):
    """Execute filter and aggregation pipelines on SQLite and PostgreSQL fixtures."""

    def _config(self) -> AnalyticsTileConfig:
        """Select fixture email/date/value columns with shared filters."""
        table = self.CustomerModel._meta.db_table
        return AnalyticsTileConfig(
            type="TABLE",
            query=f'SELECT first_name AS email_account, date_joined AS date, age AS value FROM {table}',
            filters=[
                AnalyticsTileFilter(field="email_account", type="text", shared_key="email_account"),
                AnalyticsTileFilter(field="date", type="date", shared_key="date"),
            ],
        )

    def _fixture_tiles(self) -> list[_AnalyticsFixtureTile]:
        """Return two KPI and two chart configurations sharing the same filters."""
        return [
            _AnalyticsFixtureTile(str(index), config)
            for index, config in enumerate(self.tile_configs, 1)
        ]

    def _params(self, value: str, *, lookup: str = "contains", shared: bool = False,
                with_date: bool = False) -> QueryDict:
        """Encode canonical account and optional date conditions."""
        prefix = "shared:" if shared else ""
        conditions = [FilterCondition(field_path=f"{prefix}email_account", lookup_id=lookup, value=value)]
        if with_date:
            conditions.append(FilterCondition(field_path=f"{prefix}date", lookup_id="greater_than_or_equal", value="2026-10-01"))
        params = QueryDict("", mutable=True)
        params["filter"] = json.dumps([Filter(connector="AND", conditions=conditions).model_dump()])
        return params

    def test_shared_contains_and_date_filters_feed_all_four_aggregations(self) -> None:
        """Use case: Email analysis shares account/date filters across four tiles.
        Expected result: Contains and Equals give identical real aggregate results.
        """
        # 1. Create isolated email-like fixtures with matching and nonmatching dates.
        self.CustomerModel.objects.all().delete()
        for account, joined, value in [
            ("david@example.test", date(2026, 10, 1), 1),
            ("david@example.test", date(2026, 9, 1), 0),
            ("other@example.test", date(2026, 10, 1), 99),
        ]:
            self.CustomerModel.objects.create(first_name=account, last_name="Fixture", date_joined=joined, age=value)
        self.tile_configs = [self._config() for _ in range(4)]
        for config, tile_type in zip(self.tile_configs, ["KPI", "KPI", "TWO_DIM_CHART", "TWO_DIM_CHART"]):
            config.type = tile_type
        resolver = FilterFieldResolver(workspace=SimpleNamespace(get_tiles=self._fixture_tiles))
        executor = SqlExecutor(self.admin_user)
        # 2. Run the production KPI and chart query builders, including date filtering.
        for with_date in (False, True):
            for index, config in enumerate(self.tile_configs, 1):
                results = []
                for lookup, needle in [("contains", "david"), ("equals", "david@example.test")]:
                    query = get_filtered_query(config, self._params(needle, lookup=lookup, shared=True, with_date=with_date),
                                               resolver=resolver, tile_id=str(index))
                    if index <= 2:
                        query, _ = build_kpi_aggregation_query(query, [FieldConfig(name="value", opts={"aggregator": "SUM" if index == 1 else "AVG"})])
                    else:
                        query = build_two_dim_chart_query(query, FieldConfig(name="date" if index == 3 else "email_account"), [FieldConfig(name="value")])
                    results.append(executor.execute_query(query, paginate=False))
                with self.subTest(tile=index, with_date=with_date):
                    self.assertEqual(results[0].rows, results[1].rows)
                    self.assertGreater(results[0].row_count, 0)
                    if index <= 2:
                        expected = 1 if index == 1 or with_date else 0.5
                        self.assertEqual(results[0].rows[0]["bloomerp_kpi_value_0"], expected)

    def test_special_contains_values_survive_pagination_and_policy_binding(self) -> None:
        """Use case: Account values contain quotes, percent signs, and underscores.
        Expected result: Literal matches remain safe with and without policy parameters.
        """
        # 1. Give one user access to one fixture row through a bound row policy.
        account = "O'Reilly%_!\\@example.test"
        self.CustomerModel.objects.all().delete()
        self.CustomerModel.objects.create(first_name=account, last_name="hidden", age=3)
        self.CustomerModel.objects.create(first_name="ordinary@example.test", last_name="hidden", age=9)
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={name: [BloomerpPermission.VIEW] for name in ("first_name", "date_joined", "age")},
            row_permissions=[RowPolicyRuleContent(connector="AND", permissions=[BloomerpPermission.VIEW],
                conditions=[FilterCondition(field_path="first_name", lookup_id="equals", value=account)])],
        )
        PolicyManager.assign(policy, self.normal_user)
        # 2. Exercise raw literals, bound policies, and count/page wrappers.
        for user in (None, self.admin_user, self.normal_user):
            for paginate in (False, True):
                for needle in ("O'Reilly", "%", "_", "!", "\\", "x' OR 1=1 --"):
                    with self.subTest(user=user, paginate=paginate, needle=needle):
                        query = get_filtered_query(self._config(), self._params(needle))
                        result = SqlExecutor(user).execute_query(query, paginate=paginate)
                        expected = [] if needle.startswith("x'") else [account]
                        self.assertEqual([row["email_account"] for row in result.rows], expected)
        # 3. Literal placeholder text and modulo operators coexist with bound policies.
        table = self.CustomerModel._meta.db_table
        result = SqlExecutor(self.normal_user).execute_query(
            f"SELECT '%s 100%' AS literal, age % 2 AS remainder FROM {table}", paginate=False,
        )
        self.assertEqual(result.rows, [{"literal": "%s 100%", "remainder": 1}])
