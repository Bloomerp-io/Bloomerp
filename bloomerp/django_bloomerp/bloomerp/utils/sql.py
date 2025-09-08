from django.db import connection
from django.core.cache import cache
import re
import pandas as pd
from typing import Any, List, Dict
import time

class SqlQueryExecutor:

    def __init__(self, cache_time: int = 60, cache_id: str = None):
        self.cache_time = cache_time
        self.cache_id = cache_id

    def execute_raw(self, query: str, safe: bool = True, use_cache: bool = False) -> List:
        """
        Execute a query and return the result as a list of rows.
        
        Parameters:
            - query: The SQL query to execute.
            - safe: If True, the query must be a SELECT statement, otherwise it will raise a ValueError.
            - use_cache: If True, the result will be fetched from cache if available.
        
        Returns:
            A list of rows from the executed query.
        """
        self._validate_safe_query(query, safe)
        
        if use_cache:
            cache_result = self._get_cache_result()
            if cache_result:
                return cache_result

        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchall()

        if use_cache:
            self._set_cache_result(result)

        return result

    def execute_to_dict(self, query: str, safe: bool = True, use_cache: bool = False) -> Dict[str, List]:
        """
        Execute a query and return the result as a dictionary with columns and rows.
        
        Parameters:
            - query: The SQL query to execute.
            - safe: If True, the query must be a SELECT statement, otherwise it will raise a ValueError.
            - use_cache: If True, the result will be fetched from cache if available.
        
        Returns:
            A dictionary with 'columns' and 'rows' keys.
        """
        self._validate_safe_query(query, safe)
        
        if use_cache:
            cache_result = self._get_cache_result()
            if cache_result:
                return cache_result

        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            result = {"columns": columns, "rows": rows}

        if use_cache:
            self._set_cache_result(result)

        return result

    def execute_to_first_value(self, query: str, safe: bool = True, use_cache: bool = False) -> Any:
        """
        Execute a query and return the first value of the first row.
        
        Parameters:
            - query: The SQL query to execute.
            - safe: If True, the query must be a SELECT statement, otherwise it will raise a ValueError.
            - use_cache: If True, the result will be fetched from cache if available.
        
        Returns:
            The first value of the first row from the executed query.
        """
        self._validate_safe_query(query, safe)
        
        if use_cache:
            cache_result = self._get_cache_result()
            if cache_result:
                return cache_result

        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchone()[0]

        if use_cache:
            self._set_cache_result(result)

        return result

    def execute_to_df(self, query: str, safe: bool = True, use_cache: bool = False) -> pd.DataFrame:
        """
        Execute a query and return the result as a pandas DataFrame.
        
        Parameters:
            - query: The SQL query to execute.
            - safe: If True, the query must be a SELECT statement, otherwise it will raise a ValueError.
            - use_cache: If True, the result will be fetched from cache if available.
        
        Returns:
            A pandas DataFrame containing the query result.
        """
        self._validate_safe_query(query, safe)
        
        if use_cache:
            cache_result = self._get_cache_result()
            if cache_result is not None:
                return cache_result

        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            result = pd.DataFrame(cursor.fetchall(), columns=columns)
            

        if use_cache:
            self._set_cache_result(result)

        return result

    def is_safe(self, query: str) -> bool:
        """
        Check if a query is safe to execute. Safe queries are SELECT statements.
        
        Parameters:
            - query: The SQL query to check.
        
        Returns:
            True if the query is safe, False otherwise.
        """
        return not re.search(r'\b(update|delete|insert|drop|alter|create|grant|revoke|truncate)\b', query.lower())

    def is_valid(self, query: str) -> bool:
        """
        Check if a query is valid by attempting to execute it.
        
        Parameters:
            - query: The SQL query to check.
        
        Returns:
            True if the query is valid, raises an exception otherwise.
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute(query)
            return True
        except Exception as e:
            return e

    def get_query_from_cache(self, cache_id: str) -> str:
        """
        Retrieve a query result from the cache.
        
        Parameters:
            - cache_id: The cache id to retrieve the query result.
        
        Returns:
            The cached query result.
        """
        return cache.get(cache_id)

    def _validate_safe_query(self, query: str, safe: bool):
        if not self.is_safe(query) and safe:
            raise ValueError('Unsafe query')

    def _get_cache_result(self) -> Any:
        """
        Retrieve the cached result using the cache_id.
        """
        return cache.get(self.cache_id)

    def _set_cache_result(self, result: Any):
        """
        Set the result in cache with the cache_id and cache_time.
        """
        cache.set(self.cache_id, result, self.cache_time)

