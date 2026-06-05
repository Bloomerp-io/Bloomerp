from django.http import QueryDict
from django.test import SimpleTestCase
import pandas as pd

from bloomerp.field_types.lookups import Lookup
from bloomerp.workspaces.analytics_tile.kpi import KpiAggregatedField, _build_section_vars, _render_section, _render_value, build_kpi_aggregation_query
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileFilter, get_filtered_query
from bloomerp.workspaces.analytics_tile.model import FieldConfig
from bloomerp.workspaces.analytics_tile.pie_chart import build_pie_chart_query
from bloomerp.workspaces.analytics_tile.table import _format_value
from bloomerp.workspaces.analytics_tile.two_dim_chart import build_two_dim_chart_query
from bloomerp.workspaces.analytics_tile.utils import TileFieldType

class TestAnalyticsTile(SimpleTestCase):
    def _get_config(self, query: str, filters: dict[str, AnalyticsTileFilter]) -> AnalyticsTileConfig:
        return AnalyticsTileConfig(
            query=query,
            type="table",
            fields={},
            filters=filters,
        )
    
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
                    is_variable=False
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
                    is_variable=False
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
        
        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name = 'Daniel'
        """
        
        # 4. Check
        self.assertEqual(query, expected)
        
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
                    is_variable=False
                )
            }
        )
        
        # 3. Call function
        query = get_filtered_query(config, {
            "is_active" : "Daniel"
        })
        
        ...

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
                    is_variable=False,
                )
            },
        )

        # 3. Call function with the same query parameter shape the workspace filter UI creates
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name = 'Daniel'
        """

        # 4. Check
        self.assertEqual(query, expected)

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
                    is_variable=False,
                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
        })

        expected = """SELECT * FROM (SELECT * FROM sample_table) AS filtered_query
        WHERE first_name = 'Daniel'
        """

        # 4. Check
        self.assertEqual(query, expected)
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
                    is_variable=False,
                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__icontains": "Dan",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name LIKE '%Dan%'
        """

        # 4. Check
        self.assertEqual(query, expected)

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
                    is_variable=False,
                ),
                "is_active": AnalyticsTileFilter(
                    field="is_active",
                    type=TileFieldType.BOOL.value.key,
                    is_variable=False,
                ),
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
            "is_active__exact": "true",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name = 'Daniel' AND is_active = TRUE
        """

        # 4. Check
        self.assertEqual(query, expected)

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
                    is_variable=False,
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

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name = 'Daniel'
        """

        # 4. Check
        self.assertEqual(query, expected)

    def test_get_filtered_query_with_variable_filter(self):
        # 1. Start query
        start_query = """SELECT * FROM sample_table WHERE first_name = '{{ first_name }}'"""

        # 2. Create the tile
        config = self._get_config(
            start_query,
            {
                "first_name": AnalyticsTileFilter(
                    field="first_name",
                    type=TileFieldType.TEXT.value.key,
                    is_variable=True,
                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__exact": "Daniel",
        })

        expected = """SELECT * FROM sample_table WHERE first_name = 'Daniel'"""

        # 4. Check
        self.assertEqual(query, expected)

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
                    is_variable=False
                )
            }
        )
        
        # 3. Call function
        query = get_filtered_query(config, {
            "first_name" : "Daniel"
        })
        
        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name = 'Daniel'
        """
        
        # 4. Check
        self.assertEqual(query, expected)

    def test_lookup_definitions_expose_sql_operator_functions(self):
        self.assertEqual(Lookup.EQUALS.value.sql_operator("Daniel"), "= 'Daniel'")
        self.assertEqual(Lookup.EQUALS.value.sql_operator("40"), "= 40")
        self.assertEqual(Lookup.EQUALS.value.sql_operator(40), "= 40")
        self.assertEqual(Lookup.EQUALS.value.sql_operator("true"), "= TRUE")
        self.assertEqual(Lookup.CONTAINS.value.sql_operator("Dan"), "LIKE '%Dan%'")
        self.assertEqual(Lookup.STARTS_WITH.value.sql_operator("Dan"), "LIKE 'Dan%'")
        self.assertEqual(Lookup.ENDS_WITH.value.sql_operator("son"), "LIKE '%son'")
        self.assertEqual(Lookup.GREATER_THAN.value.sql_operator("40"), "> 40")
        self.assertEqual(Lookup.GREATER_THAN_OR_EQUAL.value.sql_operator("40"), ">= 40")
        self.assertEqual(Lookup.LESS_THAN.value.sql_operator("40"), "< 40")
        self.assertEqual(Lookup.LESS_THAN_OR_EQUAL.value.sql_operator("40"), "<= 40")
        self.assertEqual(Lookup.IS_NULL.value.sql_operator("true"), "IS NULL")
        self.assertEqual(Lookup.IS_NULL.value.sql_operator("false"), "IS NOT NULL")
        self.assertEqual(Lookup.GREATER_THAN.value.sql_operator(40), "> 40")
        
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
                    is_variable=False,
                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "first_name__equals": "Daniel",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE first_name = 'Daniel'
        """

        # 4. Check
        self.assertEqual(query, expected)

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
                    is_variable=False,
                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "age__gt": "40",
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE age > 40
        """

        # 4. Check
        self.assertEqual(query, expected)

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
                    is_variable=False,
                )
            },
        )

        # 3. Call function
        query = get_filtered_query(config, {
            "age__lte": 40,
        })

        expected = f"""SELECT * FROM ({start_query}) AS filtered_query
        WHERE age <= 40
        """

        # 4. Check
        self.assertEqual(query, expected)
        
    
    
        
