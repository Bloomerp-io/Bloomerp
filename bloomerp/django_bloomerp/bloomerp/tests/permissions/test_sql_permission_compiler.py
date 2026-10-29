from django.db import connection

from bloomerp.lookups import builtins as lookups
from bloomerp.permissions.definition import (
    BloomerpPermission,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import PolicyManager, UserPolicyManager
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.names import FIRST_NAMES, LAST_NAMES


class TestSqlPermissionCompiler(BaseBloomerpTestCaseWithModels):
    def _assign_policy(self, *, fields: list[str], row_rule: RowPolicyRuleContent):
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={
                field: [BloomerpPermission.VIEW]
                for field in fields
            },
            row_permissions=[row_rule],
        )
        PolicyManager.assign(policy, self.normal_user)

    @staticmethod
    def _all_rows_rule() -> RowPolicyRuleContent:
        return RowPolicyRuleContent(
            connector="AND",
            permissions=[BloomerpPermission.VIEW],
            conditions=[RowPolicyRuleCondition(field="__all__")],
        )

    def _first_customer_rule(self) -> RowPolicyRuleContent:
        return RowPolicyRuleContent(
            connector="AND",
            permissions=[BloomerpPermission.VIEW],
            conditions=[
                RowPolicyRuleCondition(
                    field="first_name",
                    operator=lookups.EQUALS.id,
                    value=FIRST_NAMES[0],
                )
            ],
        )

    def test_compiler_filters_rows_and_masks_fields_before_user_where(self):
        """
        
        """
        self._assign_policy(
            fields=["first_name"],
            row_rule=self._first_customer_rule(),
        )
        manager = UserPolicyManager(self.normal_user)
        table = self.CustomerModel._meta.db_table

        compiled = manager.get_accessible_sql_query(
            f"SELECT first_name, last_name FROM {table} ORDER BY first_name"
        )
        self.assertIn(FIRST_NAMES[0], compiled.params)

        with connection.cursor() as cursor:
            cursor.execute(compiled.query, compiled.params)
            self.assertEqual(cursor.fetchall(), [(FIRST_NAMES[0], None)])

        inferred = manager.get_accessible_sql_query(
            f"SELECT first_name FROM {table} "
            f"WHERE last_name = '{LAST_NAMES[0]}'"
        )
        with connection.cursor() as cursor:
            cursor.execute(inferred.query, inferred.params)
            self.assertEqual(cursor.fetchall(), [])

    def test_compiler_secures_each_side_of_a_self_join(self):
        self._assign_policy(
            fields=["id", "first_name"],
            row_rule=self._all_rows_rule(),
        )
        table = self.CustomerModel._meta.db_table
        compiled = UserPolicyManager(self.normal_user).get_accessible_sql_query(
            f"SELECT c1.first_name "
            f"FROM {table} c1 "
            f"JOIN {table} c2 ON c2.id = c1.id "
            f"ORDER BY c1.first_name"
        )

        with connection.cursor() as cursor:
            cursor.execute(compiled.query, compiled.params)
            rows = cursor.fetchall()

        self.assertEqual(len(rows), self.CustomerModel.objects.count())

    def test_compiler_secures_physical_tables_inside_ctes(self):
        self._assign_policy(
            fields=["first_name"],
            row_rule=self._first_customer_rule(),
        )
        table = self.CustomerModel._meta.db_table
        compiled = UserPolicyManager(self.normal_user).get_accessible_sql_query(
            f"WITH visible AS ("
            f"SELECT first_name, last_name FROM {table}"
            f") SELECT first_name, last_name FROM visible"
        )

        with connection.cursor() as cursor:
            cursor.execute(compiled.query, compiled.params)
            self.assertEqual(cursor.fetchall(), [(FIRST_NAMES[0], None)])

    def test_compiler_rejects_unregistered_tables(self):
        self._assign_policy(
            fields=["first_name"],
            row_rule=self._all_rows_rule(),
        )

        with self.assertRaisesRegex(PermissionError, "auth_user"):
            UserPolicyManager(self.normal_user).get_accessible_sql_query(
                "SELECT username FROM auth_user"
            )

    def test_compiler_rejects_multiple_statements_and_qualified_tables(self):
        self._assign_policy(
            fields=["first_name"],
            row_rule=self._all_rows_rule(),
        )
        manager = UserPolicyManager(self.normal_user)
        table = self.CustomerModel._meta.db_table

        with self.assertRaisesRegex(ValueError, "Exactly one"):
            manager.get_accessible_sql_query(
                f"SELECT first_name FROM {table}; SELECT 1"
            )

        with self.assertRaisesRegex(PermissionError, "Qualified table"):
            manager.get_accessible_sql_query(
                f"SELECT first_name FROM main.{table}"
            )

    def test_sql_executor_uses_compiled_query_parameters(self):
        self._assign_policy(
            fields=["first_name"],
            row_rule=self._first_customer_rule(),
        )
        table = self.CustomerModel._meta.db_table

        response = SqlExecutor(self.normal_user).execute_query(
            f"SELECT first_name, last_name FROM {table}"
        )

        self.assertEqual(response.row_count, 1)
        self.assertEqual(
            response.rows,
            [{"first_name": FIRST_NAMES[0], "last_name": None}],
        )

    def test_empty_or_rule_returns_no_rows(self):
        self._assign_policy(
            fields=["first_name"],
            row_rule=RowPolicyRuleContent(connector="OR", conditions=[], permissions=[BloomerpPermission.VIEW]),
        )
        table = self.CustomerModel._meta.db_table
        compiled = UserPolicyManager(self.normal_user).get_accessible_sql_query(f"SELECT first_name FROM {table}")
        with connection.cursor() as cursor:
            cursor.execute(compiled.query, compiled.params)
            self.assertEqual(cursor.fetchall(), [])

    def test_function_escapes_are_rejected_for_every_user_before_execution(self) -> None:
        """Use case: A function attempts to read a forbidden fixture field.
        Expected result: Normal, admin, and workflow callers reject it without SQL.
        """
        # 1. Grant one fixture field, leaving last_name inaccessible.
        self._assign_policy(fields=["first_name"], row_rule=self._first_customer_rule())
        table = self.CustomerModel._meta.db_table
        queries = [
            f"SELECT query_to_xml('SELECT last_name FROM {table}', false, true, '')",
            f"SELECT COALESCE(query_to_xml('SELECT last_name FROM {table}', false, true, '')::text, '')",
            "SELECT pg_sleep(0)",
            "SELECT set_config('application_name', 'audit-only', false)",
        ]
        # 2. This also runs on disposable PostgreSQL with actual forbidden fixtures.
        for user in (self.normal_user, self.admin_user, None):
            for query in queries:
                with self.subTest(user=user, query=query), self.assertNumQueries(0):
                    with self.assertRaises(ValueError):
                        SqlExecutor(user).execute_query(query)
                    if user is not None:
                        with self.assertRaises(ValueError):
                            UserPolicyManager(user).get_accessible_sql_query(query)

    def test_supported_aggregates_use_only_permitted_rows_and_fields(self) -> None:
        """Use case: A report aggregates a table with row and field restrictions.
        Expected result: Real database results include only allowed data.
        """
        # 1. Grant only the first customer's first_name.
        self._assign_policy(fields=["first_name"], row_rule=self._first_customer_rule())
        table = self.CustomerModel._meta.db_table
        # 2. Execute real aggregates after the shared syntax and permission checks.
        response = SqlExecutor(self.normal_user).execute_query(
            f"SELECT COUNT(*) AS visible, COUNT(last_name) AS hidden, "
            f"MAX(LOWER(first_name)) AS name FROM {table}", paginate=False,
        )
        self.assertEqual(response.rows, [{"visible": 1, "hidden": 0, "name": FIRST_NAMES[0].lower()}])

    def test_recursive_report_secures_seed_and_recursive_table_references(self) -> None:
        """Use case: A reporting CTE follows relations recursively.
        Expected result: Both seed and recursive scans retain row/field masking.
        """
        # 1. Permit only one row and one field in the recursion's source table.
        self._assign_policy(fields=["first_name"], row_rule=self._first_customer_rule())
        table = self.CustomerModel._meta.db_table
        # 2. UNION terminates once the permitted row has been visited.
        result = SqlExecutor(self.normal_user).execute_query(
            f"WITH RECURSIVE visible AS (SELECT first_name, last_name FROM {table} "
            f"UNION SELECT c.first_name, c.last_name FROM {table} c "
            "JOIN visible v ON c.first_name = v.first_name) SELECT * FROM visible",
            paginate=False,
        )
        self.assertEqual(result.rows, [{"first_name": FIRST_NAMES[0], "last_name": None}])

    def test_postgres_lateral_json_expansion_uses_masked_fields(self) -> None:
        """Use case: A PostgreSQL report expands JSON made from table columns.
        Expected result: Lateral functions see permitted rows and masked fields.
        """
        # 1. Use PostgreSQL's actual JSON functions on isolated fixture data.
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL JSON integration")
        self._assign_policy(fields=["first_name"], row_rule=self._first_customer_rule())
        table = self.CustomerModel._meta.db_table
        # 2. Expanding a hidden field must produce null rather than its raw value.
        result = SqlExecutor(self.normal_user).execute_query(
            "SELECT p.value FROM " + table + " c CROSS JOIN LATERAL "
            "jsonb_array_elements_text(jsonb_build_array(c.first_name, c.last_name)) p(value)",
            paginate=False,
        )
        self.assertEqual(result.rows, [{"value": FIRST_NAMES[0]}, {"value": None}])
