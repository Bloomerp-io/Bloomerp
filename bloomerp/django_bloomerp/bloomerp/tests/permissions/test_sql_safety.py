"""Pure syntax regressions; compiler and database integration live alongside these."""

from bloomerp.permissions.compilers.sql_permission_compiler import SqlPermissionCompiler
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.utils.sql import SqlQueryExecutor
from bloomerp.utils.sql_safety import parse_read_query, validate_read_query
from django.test import SimpleTestCase


class TestSqlSafety(SimpleTestCase):
    """Verify fail-closed syntax independently of database privileges."""

    def test_rejects_function_escapes_in_every_query_position(self) -> None:
        """Use case: SQL hides ungranted reads or side effects inside expressions.
        Expected result: All nested unsafe forms fail before database execution.
        """
        # 1. Exercise function, relation, cast, and statement escape forms.
        queries = [
            "SELECT query_to_xml('SELECT secret FROM forbidden_marker', false, true, '')",
            "SELECT COALESCE(query_to_xml('SELECT secret FROM forbidden_marker', false, true, '')::text, '')",
            "WITH a AS (SELECT pg_sleep(0)) SELECT * FROM a",
            "SELECT 1 WHERE set_config('application_name', 'changed', false) IS NULL",
            "SELECT 1 ORDER BY pg_read_file('/unused')",
            "SELECT * FROM dblink('unused', 'SELECT secret FROM forbidden_marker')",
            "SELECT custom_function(1)",
            "SELECT * FROM jsonb_array_elements_text(query_to_xml('SELECT secret FROM forbidden_marker', false, true, '')::jsonb)",
            "SELECT * FROM generate_series(1, 1000000000)",
            "SELECT pg_catalog.query_to_xml('SELECT 1', false, true, '')",
            "SELECT public.lower('a')",
            "SELECT CAST('a' AS public.custom_type)",
            "SELECT 'forbidden_marker'::regclass",
            "SELECT nextval('unused')",
            "SELECT 1 INTO new_table",
            "SELECT * FROM allowed FOR UPDATE",
            "WITH a AS (DELETE FROM allowed RETURNING *) SELECT * FROM a",
            "SELECT 1; SELECT 2",
        ]
        # 2. Direct compilation cannot bypass the shared syntax policy.
        for query in queries:
            with self.subTest(query=query), self.assertRaises(ValueError):
                SqlPermissionCompiler({}).compile(query, dialect="postgres")

    def test_preserves_reporting_expressions_and_literal_keywords(self) -> None:
        """Use case: Reports combine aggregation, windows, dates and text literals.
        Expected result: Reviewed SQL remains accepted without lexical false positives.
        """
        # 1. Keep realistic report grammar and harmless keyword-containing text.
        queries = [
            "SELECT COUNT(*), SUM(x), AVG(x), MIN(x), MAX(x), ROUND(AVG(x), 2) FROM t",
            "SELECT COALESCE(SUM(x), 0) / NULLIF(COUNT(*), 0) FROM t",
            "SELECT COUNT(*) FILTER (WHERE x > 0), STRING_AGG(y, ',') FROM t",
            "SELECT DATE_TRUNC('month', d), EXTRACT(YEAR FROM d), TO_CHAR(d, 'YYYY') FROM t",
            "WITH a AS (SELECT x FROM t) SELECT ROW_NUMBER() OVER (ORDER BY x), x FROM a",
            "SELECT CASE WHEN x IN (1, 2) THEN 'delete; update' ELSE 'create' END FROM t",
            "SELECT first_name FROM t WHERE first_name LIKE 'a%' UNION ALL SELECT 'other'",
            "SELECT CAST(x AS numeric(12, 2)), CURRENT_DATE, NOW() FROM t",
            "SELECT LOWER(x), UPPER(x), REPLACE(x, 'a', 'b') FROM t",
            "SELECT x FROM t WHERE x ILIKE E'%O''Reilly%'",
            "SELECT $$pg_sleep(0); delete$$ AS literal",
            "SELECT DATE_TRUNC('day', d AT TIME ZONE 'UTC') FROM t",
            "WITH RECURSIVE chain AS (SELECT 1 AS n UNION SELECT n + 1 FROM chain WHERE n < 3) SELECT * FROM chain",
            "SELECT jsonb_array_length(data), data ? 'Sent' FROM t",
            "SELECT p.email FROM t CROSS JOIN LATERAL jsonb_array_elements_text(t.data) p(email)",
            "SELECT REGEXP_REPLACE(url, '^https?://', '') FROM t",
        ]
        # 2. Validate without accessing any database or policy metadata.
        for query in queries:
            with self.subTest(query=query):
                validate_read_query(query, "postgres")
        validate_read_query("SELECT strftime('%Y', d), julianday(d) FROM t", "sqlite")

    def test_cached_trees_are_isolated_from_permission_rewrites(self) -> None:
        """Use case: Different users compile identical SQL from the syntax cache.
        Expected result: Mutating one tree cannot alter the next user's input.
        """
        # 1. Mutate one returned tree as a compiler would.
        first = parse_read_query("SELECT 1", "postgres")
        first.set("limit", None)
        first.set("expressions", [])
        # 2. A new caller receives the unchanged validated query.
        self.assertEqual(parse_read_query("SELECT 1", "postgres").sql(), "SELECT 1")

    def test_executor_variants_reject_before_opening_a_cursor(self) -> None:
        """Use case: Workflow and low-level SQL callers use the read-only executor.
        Expected result: Unsafe functions never reach a cursor through any variant.
        """
        # 1. Exercise the shared SQL executor and its low-level safe defaults.
        query = "SELECT pg_sleep(0)"
        raw = SqlQueryExecutor()
        for execute in (
            SqlExecutor().execute_query,
            raw.execute_raw,
            raw.execute_to_dict,
            raw.execute_to_df,
            raw.execute_to_first_value,
        ):
            with (
                self.subTest(execute=execute.__name__),
                self.assertRaises(ValueError),
            ):
                execute(query)
        self.assertIsInstance(raw.is_valid(query), ValueError)
        # 2. SimpleTestCase forbids database access for every call above.

    def test_json_expansion_cannot_hide_an_ungranted_subquery(self) -> None:
        """Use case: A permitted JSON expansion receives a relational subquery.
        Expected result: Physical tables inside its arguments still require grants.
        """
        # 1. Reference a forbidden fixture table inside a reviewed JSON function.
        query = "SELECT * FROM jsonb_array_elements_text((SELECT secret FROM forbidden_marker)) AS item(value)"
        # 2. Table authorization must reject it even though the function is safe.
        with self.assertRaisesRegex(PermissionError, "forbidden_marker"):
            SqlPermissionCompiler({}).compile(query, dialect="postgres")
