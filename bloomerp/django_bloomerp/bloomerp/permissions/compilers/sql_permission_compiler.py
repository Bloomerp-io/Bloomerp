import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from django.core.exceptions import EmptyResultSet
from django.db import connection
from django.db.models import Model, Q
from sqlglot import exp, parse, parse_one
from sqlglot.optimizer.scope import traverse_scope

from bloomerp.permissions.compilers.base import BasePermissionCompiler
from bloomerp.permissions.compilers.django_q_permission_compiler import (
    CompiledDjangoAccess,
    DjangoQPermissionCompiler,
)
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch


@dataclass(frozen=True)
class CompiledSqlAccess:
    query: str
    params: tuple[Any, ...] = ()
    denied: bool = False


def get_table_names(sql: str, dialect: str = "postgres") -> set[str]:
    tree = parse_one(sql, read=dialect)
    return {table.name for table in tree.find_all(exp.Table)}


def get_physical_tables(sql: str, dialect: str = "postgres") -> list[exp.Table]:
    return SqlPermissionCompiler._physical_tables_from_tree(
        SqlPermissionCompiler._parse_single_read_query(sql, dialect)
    )


def get_table_references(sql: str, dialect: str = "postgres") -> list[dict[str, str]]:
    return [
        {
            "catalog": table.catalog,
            "schema": table.db,
            "table": table.name,
            "alias": table.alias or table.name,
        }
        for table in get_physical_tables(sql, dialect)
    ]


class SqlPermissionCompiler(BasePermissionCompiler[CompiledSqlAccess]):
    """Apply row and field policies to user-authored read-only SQL."""

    def compile(
        self,
        query: str,
        permissions=BloomerpPermission.VIEW,
        match: PermissionMatch = PermissionMatch.ANY,
        *,
        dialect: str | None = None,
    ) -> CompiledSqlAccess:
        dialect = dialect or self._connection_dialect()
        tree = self._parse_single_read_query(query, dialect)
        physical_tables = self._physical_tables_from_tree(tree)
        models_by_table: dict[str, type[Model]] = {}
        for model in self.rules:
            table_name = model._meta.db_table
            if table_name in models_by_table and models_by_table[table_name] is not model:
                raise PermissionError(f"Ambiguous model mapping for table: {table_name}")
            models_by_table[table_name] = model

        for table in physical_tables:
            if table.catalog or table.db:
                raise PermissionError(
                    f"Qualified table names are not allowed: {table.sql(dialect=dialect)}"
                )
            if table.name not in models_by_table:
                raise PermissionError(f"You do not have access to table: {table.name}")

        marker_prefix = f"__bloomerp_policy_param_{uuid4().hex}_"
        marker_values: dict[int, Any] = {}
        for occurrence, table in enumerate(physical_tables):
            model = models_by_table[table.name]
            compiled_access = DjangoQPermissionCompiler(
                self.rules[model],
                user=self.user,
                model=model,
            ).compile(permissions, match)
            table.replace(
                self._secure_table_expression(
                    model=model,
                    original_table=table,
                    compiled_access=compiled_access,
                    marker_prefix=marker_prefix,
                    marker_values=marker_values,
                    occurrence=occurrence,
                )
            )

        compiled_query = tree.sql(dialect=dialect)
        marker_pattern = re.compile(rf"{re.escape(marker_prefix)}(\d+)__")
        ordered_params = []

        def replace_marker(match_object: re.Match) -> str:
            marker_index = int(match_object.group(1))
            ordered_params.append(marker_values[marker_index])
            return "%s"

        compiled_query = marker_pattern.sub(replace_marker, compiled_query)
        if len(ordered_params) != len(marker_values):
            raise ValueError("Could not preserve all SQL policy parameters")
        return CompiledSqlAccess(compiled_query, tuple(ordered_params))

    @staticmethod
    def _connection_dialect() -> str:
        dialects = {"postgresql": "postgres", "sqlite": "sqlite"}
        try:
            return dialects[connection.vendor]
        except KeyError as exc:
            raise ValueError(f"Unsupported SQL permission dialect: {connection.vendor}") from exc

    @staticmethod
    def _parse_single_read_query(query: str, dialect: str) -> exp.Query:
        statements = [statement for statement in parse(query, read=dialect) if statement]
        if len(statements) != 1:
            raise ValueError("Exactly one SQL statement is required")
        statement = statements[0]
        if not isinstance(statement, exp.Query) or statement.find(exp.Into):
            raise ValueError("Only read-only SELECT/WITH queries are allowed")
        return statement

    @staticmethod
    def _physical_tables_from_tree(tree: exp.Query) -> list[exp.Table]:
        tables = []
        for scope in traverse_scope(tree):
            for table in scope.tables:
                if (
                    isinstance(table, exp.Table)
                    and table.name
                    and table.name not in scope.cte_sources
                ):
                    tables.append(table)
        return tables

    @classmethod
    def _secure_table_expression(
        cls,
        *,
        model: type[Model],
        original_table: exp.Table,
        compiled_access: CompiledDjangoAccess,
        marker_prefix: str,
        marker_values: dict[int, Any],
        occurrence: int,
    ) -> exp.Subquery:
        raw_alias = f"__bloomerp_raw_{occurrence}"
        output_alias = original_table.alias or original_table.name
        raw_table = exp.Table(
            this=exp.to_identifier(model._meta.db_table),
            alias=exp.TableAlias(this=exp.to_identifier(raw_alias)),
        )
        field_predicates: dict[str, Q] = {}
        for row_filter, application_fields in compiled_access.field_filters.items():
            for application_field in application_fields:
                field_name = application_field.field
                existing = field_predicates.get(field_name)
                field_predicates[field_name] = (
                    row_filter if existing is None else existing | row_filter
                )

        projections = []
        for model_field in model._meta.concrete_fields:
            column_name = model_field.column
            raw_column = exp.column(column_name, table=raw_alias)
            field_predicate = field_predicates.get(model_field.name)
            if field_predicate is None:
                condition = exp.false()
            else:
                field_subquery = cls._pk_subquery(
                    model, field_predicate, marker_prefix, marker_values
                )
                condition = exp.In(
                    this=exp.column(model._meta.pk.column, table=raw_alias),
                    query=exp.Subquery(this=exp.Var(this=field_subquery)),
                )
            projections.append(
                exp.Case(
                    ifs=[exp.If(this=condition, true=raw_column)],
                    default=exp.Null(),
                ).as_(column_name)
            )

        row_subquery = cls._pk_subquery(
            model, compiled_access.row_filter, marker_prefix, marker_values
        )
        secured_select = (
            exp.Select(expressions=projections)
            .from_(raw_table)
            .where(
                exp.In(
                    this=exp.column(model._meta.pk.column, table=raw_alias),
                    query=exp.Subquery(this=exp.Var(this=row_subquery)),
                )
            )
        )
        return exp.Subquery(
            this=secured_select,
            alias=exp.TableAlias(this=exp.to_identifier(output_alias)),
        )

    @staticmethod
    def _pk_subquery(
        model: type[Model],
        row_filter: Q,
        marker_prefix: str,
        marker_values: dict[int, Any],
    ) -> str:
        queryset = (
            model.objects.filter(row_filter)
            .order_by()
            .values_list(model._meta.pk.attname, flat=True)
            .distinct()
        )
        try:
            sql, params = queryset.query.sql_with_params()
        except EmptyResultSet:
            quote = connection.ops.quote_name
            return f"SELECT {quote(model._meta.pk.column)} FROM {quote(model._meta.db_table)} WHERE 1 = 0"
        if sql.count("%s") != len(params):
            raise ValueError("Unexpected SQL parameter format from Django")
        for value in params:
            marker_index = len(marker_values)
            marker = f"{marker_prefix}{marker_index}__"
            sql = sql.replace("%s", marker, 1)
            marker_values[marker_index] = value
        return sql
