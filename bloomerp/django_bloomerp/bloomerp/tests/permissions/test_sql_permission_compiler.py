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
