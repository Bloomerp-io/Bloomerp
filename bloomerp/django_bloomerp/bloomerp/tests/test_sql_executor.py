


from bloomerp.services.sql_services import SqlExecutor
from bloomerp.tests.base import BaseBloomerpModelTestCase

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
        
        