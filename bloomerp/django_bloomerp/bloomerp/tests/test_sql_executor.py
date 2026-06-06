
from unittest.mock import patch

from bloomerp.services.sql_services import SqlExecutor
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.utils.sql import SqlQueryExecutor

class TestSqlExecutor(BaseBloomerpModelTestCase):
    def extendedSetup(self):
        self.db_table = self.CustomerModel._meta.db_table
        
        self.executor = SqlExecutor(self.admin_user)
    
    def test_unsafe_query_drop(self):
        """
        Tests whether a query is valid as safe
        """
        # 1. Create query
        query = f"""
        DROP TABLE {self.db_table};
        """
        
        # 2. Check if flagged as unsafe
        self.assertFalse(
            self.executor.is_safe(query)
        )
        
    def test_unsafe_query_delete(self):
        """
        Tests whether a DELETE query is flagged as unsafe
        """
        query = f"""
        DELETE FROM {self.db_table} WHERE id = 1;
        """
        self.assertFalse(self.executor.is_safe(query))

    def test_unsafe_query_truncate(self):
        """
        Tests whether a TRUNCATE query is flagged as unsafe
        """
        query = f"""
        TRUNCATE TABLE {self.db_table};
        """
        self.assertFalse(self.executor.is_safe(query))

    def test_unsafe_query_alter(self):
        """
        Tests whether an ALTER TABLE query is flagged as unsafe
        """
        query = f"""
        ALTER TABLE {self.db_table} DROP COLUMN name;
        """
        self.assertFalse(self.executor.is_safe(query))

    def test_safe_query_select(self):
        """
        Tests whether a SELECT query is flagged as safe
        """
        query = f"""
        SELECT * FROM {self.db_table};
        """
        self.assertTrue(self.executor.is_safe(query))

    def test_extract_referenced_tables_ignores_cte_names(self):
        """
        Tests whether CTE aliases are not treated as database tables.
        """
        query = f"""
        WITH bloomerp_kpi_source AS (
            SELECT id FROM {self.db_table}
        ),
        bloomerp_kpi_numbered AS (
            SELECT * FROM bloomerp_kpi_source
        )
        SELECT COUNT("id") FROM bloomerp_kpi_numbered;
        """

        self.assertEqual(
            self.executor._extract_referenced_tables(query),
            {self.db_table},
        )

    def test_raw_postgres_type_code_falls_back_to_backend_type_map(self):
        """
        Tests whether raw cursor type codes still resolve when introspection fails.
        """
        executor = SqlQueryExecutor()

        with patch(
            "bloomerp.utils.sql.connection.introspection.get_field_type",
            side_effect=AttributeError("raw cursor metadata"),
        ), patch(
            "bloomerp.utils.sql.connection.introspection.data_types_reverse",
            {701: "FloatField"},
        ):
            field_type = executor._get_field_type((None, 701))

        self.assertEqual(field_type, "floatfield")

    def test_output_field_type_uses_numeric_row_value_when_metadata_is_unknown(self):
        """
        Tests whether computed numeric columns are not downgraded without metadata.
        """
        field_type = self.executor._resolve_output_field_type(
            "total",
            "unknown",
            [{"total": 12.5}],
        )

        self.assertEqual(field_type, "numeric")

    def test_output_field_type_keeps_text_when_metadata_and_value_are_text(self):
        """
        Tests whether real text columns stay text when sampled.
        """
        field_type = self.executor._resolve_output_field_type(
            "activity",
            "text",
            [{"activity": "Development"}],
        )

        self.assertEqual(field_type, "text")

    def test_output_field_type_does_not_assume_id_columns_are_numeric(self):
        """
        Tests whether ID column names alone do not force numeric output types.
        """
        field_type = self.executor._resolve_output_field_type(
            "external_id",
            "unknown",
            [],
        )

        self.assertEqual(field_type, "text")
