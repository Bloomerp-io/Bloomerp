from django.http import QueryDict
from django.test import SimpleTestCase

from bloomerp.field_types.lookups import Lookup
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileFilter, get_filtered_query
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
        
    
    
        
