from django.core.exceptions import ValidationError as FilterValidationError
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase
import pandas as pd
from pydantic import ValidationError

from bloomerp.lookups import builtins as lookups
from bloomerp.lookups.definition import BoundLookup, SQLLookupContext
from bloomerp.workspaces.analytics_tile.kpi import KpiAggregatedField, _build_section_vars, _render_section, _render_value, build_kpi_aggregation_query
from bloomerp.workspaces.analytics_tile.model import (
    AddFilterHandler,
    AddFilterOperation,
    AnalyticsTileConfig,
    AnalyticsTileFilter,
    FieldConfig,
    RemoveFilterHandler,
    RemoveFilterOperation,
    get_filtered_query,
)
from bloomerp.workspaces.analytics_tile.pie_chart import build_pie_chart_query
from bloomerp.workspaces.analytics_tile.table import _format_value
from bloomerp.workspaces.analytics_tile.two_dim_chart import build_two_dim_chart_query
from bloomerp.workspaces.analytics_tile.utils import TileFieldType

class TestAnalyticsTile(SimpleTestCase):
    def assert_query(self, query, expected):
        # Expectations use PostgreSQL literals; SQLite uses ordinary literals.
        if connection.vendor != "postgresql":
            expected = expected.replace("E'", "'")
        self.assertEqual(query, expected)

    def _get_config(
        self,
        query: str,
        filters: list[AnalyticsTileFilter] | dict[str, AnalyticsTileFilter],
    ) -> AnalyticsTileConfig:
        return AnalyticsTileConfig(
            query=query,
            type="table",
            fields={},
            filters=filters,
        )

    def test_filter_list_is_serialized_as_a_list(self):
        config = self._get_config(
            "SELECT * FROM sample_table",
            [AnalyticsTileFilter(field="first_name", type="text")],
        )

        self.assertEqual(config.filters[0].field, "first_name")
        self.assertIsInstance(config.model_dump()["filters"], list)

    def test_legacy_filter_dict_is_normalized_to_a_list(self):
        config = self._get_config(
            "SELECT * FROM sample_table",
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type="text",
                )
            },
        )

        self.assertEqual(
            config.filters,
            [AnalyticsTileFilter(field="first_name", type="text")],
        )
        self.assertIsInstance(config.model_dump()["filters"], list)

    def test_filter_fields_must_be_unique(self):
        with self.assertRaisesRegex(
            ValidationError,
            "Analytics tile filter fields must be unique",
        ):
            self._get_config(
                "SELECT * FROM sample_table",
                [
                    AnalyticsTileFilter(field="first_name", type="text"),
                    AnalyticsTileFilter(field="first_name", type="text"),
                ],
            )

    def test_add_and_remove_filter_handlers_use_filter_lists(self):
        config = self._get_config("SELECT * FROM sample_table", [])

        AddFilterHandler.handle(
            config,
            AddFilterOperation(field="first_name", type="text"),
        )

        self.assertEqual(
            config.filters,
            [AnalyticsTileFilter(field="first_name", type="text")],
        )

        RemoveFilterHandler.handle(
            config,
            RemoveFilterOperation(field="first_name"),
        )

        self.assertEqual(config.filters, [])
    
    def test_get_filtered_query_with_non_defined_filter(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""
        
        # 2. Create the tile
        config = AnalyticsTileConfig(
            query=start_query,
            type="table",
            fields={},
            filters={
                "first_name" : AnalyticsTileFilter(
                    field="first_name",
                    type="text",

                )
            }
        )
        
        # 3. Call function
        query = get_filtered_query(config, {
            "non_defined_filter" : 40
        })
        
        # 4. Check
        self.assertEqual(query, start_query)

    def test_format_value_renders_advanced_formatting_with_value_context(self):
        field = FieldConfig(
            name="total",
            opts={
                "advanced_formatting": "USD {{ value }}",
            },
        )

        rendered = _format_value(42, field, {})

        self.assertEqual(rendered, "USD 42")

    def test_render_value_renders_advanced_formatting_with_formatted_and_preformatted_values(self):
        revenue_field = FieldConfig(
            name="Revenue",
            opts={
                "formatter": "CURRENCY_USD",
            },
        )
        aggregated_fields = [
            KpiAggregatedField(field=revenue_field, alias="bloomerp_kpi_value_0"),
        ]

        rendered = _render_section(
            aggregated_fields,
            pd.DataFrame({"bloomerp_kpi_value_0": [42]}),
            "raw={{ preformatted_var_revenue }} formatted={{ var_revenue }}",
        )

        self.assertEqual(rendered, "raw=42 formatted=$42.00")

    def test_render_section_allows_multiple_kpi_values_in_one_template(self):
        revenue_field = FieldConfig(name="Revenue")
        orders_field = FieldConfig(name="Orders")
        aggregated_fields = [
            KpiAggregatedField(field=revenue_field, alias="bloomerp_kpi_value_0"),
            KpiAggregatedField(field=orders_field, alias="bloomerp_kpi_value_1"),
        ]
        data = pd.DataFrame(
            {
                "bloomerp_kpi_value_0": [42],
                "bloomerp_kpi_value_1": [3],
            }
        )

        rendered = _render_section(
            aggregated_fields,
            data,
            "Revenue {{ var_revenue }} across {{ var_orders }} orders",
        )

        self.assertEqual(rendered, "Revenue 42 across 3 orders")

    def test_render_section_uses_default_when_advanced_formatting_is_blank(self):
        revenue_field = FieldConfig(name="Revenue")
        aggregated_fields = [
            KpiAggregatedField(field=revenue_field, alias="bloomerp_kpi_value_0"),
        ]

        rendered = _render_section(
            aggregated_fields,
            pd.DataFrame({"bloomerp_kpi_value_0": [42]}),
            "   ",
        )

        self.assertEqual(rendered, "42")

    def test_build_section_vars_includes_formatted_and_preformatted_values(self):
        aggregated_fields = [
            KpiAggregatedField(field=FieldConfig(name="Revenue"), alias="bloomerp_kpi_value_0"),
        ]
        aggregated_data = pd.DataFrame({"bloomerp_kpi_value_0": [42]})

        vars = _build_section_vars(aggregated_fields, aggregated_data)

        self.assertEqual(vars["var_revenue"], "42")
        self.assertEqual(vars["preformatted_var_revenue"], 42)
        
    def test_get_filtered_query_with_text_column(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""
        
        # 2. Create the tile
        config = self._get_config(
            query=start_query,
            filters={
                "first_name" : AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            }
        )
        
        # 3. Call function
        query = get_filtered_query(
            config, 
            {
                "first_name" : "Daniel"
            }
        )
        
        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" = E'Daniel'))"""
        
        # 4. Check
        self.assert_query(query, expected)
        
    def test_get_filtered_query_with_bool_column(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""
        
        # 2. Create the tile
        config = AnalyticsTileConfig(
            query=start_query,
            type="table",
            fields={},
            filters={
                "is_active" : AnalyticsTileFilter(
                    field="is_active",
                    type=TileFieldType.BOOL.value.key,

                )
            }
        )
        
        # 3. Call function
        with self.assertRaises(FilterValidationError):
            get_filtered_query(config, {"is_active": "Daniel"})

    def test_get_filtered_query_with_lookup_query_param(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            },
        )

        # 3. Call function with the same query parameter shape the workspace filter UI creates
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" = E'Daniel'))"""

        # 4. Check
        self.assert_query(query, expected)

    def test_get_filtered_query_strips_base_query_trailing_semicolon(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table;"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
        })

        expected = """SELECT * FROM (SELECT * FROM sample_table) AS filtered_query WHERE (("first_name" = E'Daniel'))"""

        # 4. Check
        self.assert_query(query, expected)
        self.assertNotIn(";", query)

    def test_get_filtered_query_with_contains_lookup_query_param(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__icontains": "Dan",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" ILIKE E'%Dan%'))"""

        # 4. Check
        self.assert_query(query, expected)

    def test_get_filtered_query_with_multiple_defined_filters(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                ),
                "is_active": AnalyticsTileFilter(
                    field="is_active",
                    type=TileFieldType.BOOL.value.key,

                ),
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
            "is_active__exact": "true",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" = E'Daniel')) AND (("is_active" = TRUE))"""

        # 4. Check
        self.assert_query(query, expected)

    def test_get_filtered_query_ignores_layout_tile_params(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            },
        )

        # 3. Call function with params added to each workspace tile render request
        query = get_filtered_query(config, {
            "tile_id": "1",
            "colspan": "2",
            "max_cols": "4",
            "first_name__exact": "Daniel",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" = E'Daniel'))"""

        # 4. Check
        self.assert_query(query, expected)

    def test_build_kpi_aggregation_query_applies_count_in_sql(self):
        # 1. Create query and KPI field config
        start_query = """SELECT id, first_name FROM sample_table"""
        field = FieldConfig(
            name="id",
            opts={
                "aggregator": "COUNT",
                "formatter": "INTEGER",
            },
        )

        # 2. Build KPI aggregation query
        query, aggregated_fields = build_kpi_aggregation_query(start_query, [field])

        # 3. Check the KPI executes a SQL aggregation over the full filtered source
        self.assertIn("WITH bloomerp_kpi_source AS", query)
        self.assertIn(start_query, query)
        self.assertIn('COUNT("id") AS "bloomerp_kpi_value_0"', query)
        self.assertIn("FROM bloomerp_kpi_source", query)
        self.assertIn('AS "bloomerp_kpi_value_0"', query)
        self.assertEqual(aggregated_fields[0].field, field)
        self.assertEqual(aggregated_fields[0].alias, "bloomerp_kpi_value_0")

    def test_build_kpi_aggregation_query_escapes_identifier_quotes(self):
        # 1. Create a field name containing a double quote
        field = FieldConfig(
            name='odd"field',
            opts={
                "aggregator": "SUM",
            },
        )

        # 2. Build KPI aggregation query
        query, _ = build_kpi_aggregation_query("SELECT 1 AS value", [field])

        # 3. Check the identifier is quoted safely
        self.assertIn('SUM("odd""field") AS "bloomerp_kpi_value_0"', query)

    def test_build_pie_chart_query_groups_values_in_sql(self):
        # 1. Create query and pie chart field config
        start_query = """SELECT department, salary FROM employees"""
        label_field = FieldConfig(name="department", opts={})
        value_field = FieldConfig(name="salary", opts={})

        # 2. Build pie chart aggregation query
        query = build_pie_chart_query(start_query, label_field, value_field)

        # 3. Check slice totals are calculated by SQL
        self.assertIn("WITH bloomerp_pie_source AS", query)
        self.assertIn(start_query, query)
        self.assertIn('SELECT "department" AS "bloomerp_pie_label"', query)
        self.assertIn('SUM("salary") AS "bloomerp_pie_value"', query)
        self.assertIn('GROUP BY "department"', query)

    def test_build_two_dim_chart_query_groups_series_in_sql(self):
        # 1. Create query and 2D chart field config
        start_query = """SELECT month, revenue, cost FROM sales"""
        x_axis_field = FieldConfig(name="month", opts={})
        y_axis_fields = [
            FieldConfig(name="revenue", opts={}),
            FieldConfig(name="cost", opts={}),
        ]

        # 2. Build 2D chart aggregation query
        query = build_two_dim_chart_query(start_query, x_axis_field, y_axis_fields)

        # 3. Check series values are calculated by SQL before Plotly receives data
        self.assertIn("WITH bloomerp_chart_source AS", query)
        self.assertIn(start_query, query)
        self.assertIn('SELECT "month" AS "bloomerp_chart_x_axis"', query)
        self.assertIn('SUM("revenue") AS "bloomerp_chart_y_axis_0"', query)
        self.assertIn('SUM("cost") AS "bloomerp_chart_y_axis_1"', query)
        self.assertIn('GROUP BY "month"', query)
        self.assertIn('ORDER BY "month"', query)
        
    def test_get_filtered_query_with_equals_operator(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""
        
        # 2. Create the tile
        config = AnalyticsTileConfig(
            query=start_query,
            type="table",
            fields={},
            filters={
                "first_name" : AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            }
        )
        
        # 3. Call function
        query = get_filtered_query(config, {
            "first_name" : "Daniel"
        })
        
        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" = E'Daniel'))"""
        
        # 4. Check
        self.assert_query(query, expected)

    def test_lookup_definitions_expose_parameterized_sql_factories(self):
        """
        UC: Compile equality through the registered lookup factory.
        Expected Result: Values remain parameters rather than being interpolated into SQL.
        """
        lookup = BoundLookup.normalize(lookups.EQUALS)
        for value in ["Daniel", "40", 40, True]:
            with self.subTest(value=value):
                compiled = lookup.get_sql_factory()(SQLLookupContext(field_path='"name"'), lookup.expressions[0], value)
                self.assertEqual(compiled.clause, '"name" = %s')
                self.assertEqual(compiled.parameters, (value,))

    def test_get_filtered_query_resolves_equals_lookup_from_alias(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,

                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__equals": "Daniel",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("first_name" = E'Daniel'))"""

        # 4. Check
        self.assert_query(query, expected)

    def test_get_filtered_query_resolves_numeric_lookup_from_alias(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "age": AnalyticsTileFilter(
                    field="age",
                    type=TileFieldType.NUMERIC.value.key,

                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "age__gt": "40",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("age" > 40))"""

        # 4. Check
        self.assert_query(query, expected)

    def test_get_filtered_query_resolves_less_than_or_equal_lookup_from_alias(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "age": AnalyticsTileFilter(
                    field="age",
                    type=TileFieldType.NUMERIC.value.key,

                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "age__lte": 40,
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query WHERE (("age" <= 40))"""

        # 4. Check
        self.assert_query(query, expected)
        
    
    
        

    def test_shared_key_operation_updates_and_clears(self):
        """
        UC: Edit an analytics filter's optional shared key in the builder.
        Expected Result: The key persists through serialization, and clearing restores the column name.
        """
        config = self._get_config('SELECT first_name FROM sample_table', [AnalyticsTileFilter(field='first_name', type='text')])
        operation = config.get_operation('set_filter_shared_key')
        operation.handler.handle(config, operation.validation_model(field='first_name', shared_key=' name '))
        restored = AnalyticsTileConfig.model_validate(config.model_dump())
        self.assertEqual(restored.get_filter_shared_key('first_name'), 'name')
        operation.handler.handle(restored, operation.validation_model(field='first_name', shared_key=''))
        self.assertIsNone(restored.filters[0].shared_key)
        self.assertEqual(restored.get_filter_shared_key('first_name'), 'first_name')

    def test_shared_key_operation_rejects_invalid_key(self):
        """
        UC: Submit a shared key containing the path delimiter.
        Expected Result: Validation rejects it without modifying the filter.
        """
        config = self._get_config('SELECT first_name FROM sample_table', [AnalyticsTileFilter(field='first_name', type='text')])
        operation = config.get_operation('set_filter_shared_key')
        with self.assertRaises(ValidationError):
            operation.handler.handle(config, operation.validation_model(field='first_name', shared_key='bad:key'))
        self.assertIsNone(config.filters[0].shared_key)

    def test_filter_does_not_substitute_sql_placeholders(self):
        """
        UC: A query contains a placeholder that used to be a variable filter.
        Expected Result: Filtering only adds an output-column predicate; the SQL text is not substituted.
        """
        config = self._get_config("SELECT '{{ first_name }}' AS first_name", [AnalyticsTileFilter(field='first_name', type='text')])
        self.assertIn('{{ first_name }}', get_filtered_query(config, {'first_name': 'David'}))

    def test_builder_renders_optional_shared_key(self):
        """
        UC: Open the analytics builder with an existing shared key.
        Expected Result: The filter editor shows the saved key and posts the dedicated operation.
        """
        from bs4 import BeautifulSoup
        from django.template.loader import render_to_string
        config = self._get_config('SELECT first_name FROM sample_table', [AnalyticsTileFilter(field='first_name', type='text', shared_key='name')])
        html = render_to_string('components/workspaces/tiles/builders/analytics.html', {'config': config})
        soup = BeautifulSoup(html, 'html.parser')
        field = soup.select_one('input[name="shared_key"]')
        self.assertIsNotNone(field)
        self.assertEqual(field['value'], 'name')
        self.assertEqual(field['placeholder'], 'first_name')
        self.assertFalse(field.has_attr('required'))
        self.assertIn('set_filter_shared_key', field.find_parent('form')['hx-vars'])
