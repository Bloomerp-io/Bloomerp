import re
import time
from typing import Any

import pandas as pd

from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.utils.sql import SqlQueryExecutor
from bloomerp.workspaces.analytics_tile.utils import TileFieldType, get_primitive_field_icon, to_primitive_field_type
from pydantic import BaseModel

from bloomerp.workspaces.utils import UserParameterResolver

class Field(BaseModel):
    """Represents one selectable SQL output field or accessible database field."""

    name:str
    field_type:str
    icon:str = "fa-solid fa-table-columns"
    permissions:list[str] = []

class DatabaseTable(BaseModel):
    """Represents a table-like collection of fields for the SQL builder."""

    name:str
    icon:str = "fa-solid fa-table"
    content_type_id:int | None = None
    fields:list[Field]

    def model_dump(self, *args, include_field_icons: bool = True, **kwargs) -> dict:
        data = super().model_dump(*args, **kwargs)
        if include_field_icons:
            return data

        for field in data.get("fields", []):
            if isinstance(field, dict):
                field.pop("icon", None)
        return data


class SqlQueryResponse(BaseModel):
    """Structured SQL response used by the SQL preview and analytics builder."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    page_rows_count: int
    execution_ms: int
    policy_message: str | None = None
    page: int
    page_size: int
    total_pages: int
    page_start: int
    page_end: int
    output_fields: DatabaseTable | None = None
    
    def to_dataframe(self) -> pd.DataFrame:
        """Creates a DataFrame from the already materialized response rows."""
        if not self.rows:
            return pd.DataFrame(columns=self.columns)

        return pd.DataFrame.from_records(self.rows, columns=self.columns)


class SqlExecutor:
    """
    Class for executing SQL query within the app.
    """
    REQUIRED_PERMISSION = BloomerpPermission.VIEW

    def __init__(self, user: AbstractBloomerpUser | None = None):
        self.user = user
        self.policy_manager = UserPolicyManager(user) if user else None

    def get_accessible_tables_and_fields(self) -> list[DatabaseTable]:
        """Returns the accessible tables and fields for 
        the user.

        Returns:
            list[DatabaseTable]: list of database tables with fields
        """
        models_and_fields = self.policy_manager.get_accessible_models_and_fields(
            self.REQUIRED_PERMISSION
        )

        tables: list[DatabaseTable] = []
        for model, fields in models_and_fields.items():
            table_name = model._meta.db_table
            field_list: list[Field] = []
            for field in fields:
                field_list.append(
                    Field(
                        name=field.field,
                        field_type=field.field_type,
                        icon=get_primitive_field_icon(field.field_type),
                    )
                )
            tables.append(
                DatabaseTable(
                    name=table_name,
                    fields=field_list,
                )
            )

        return tables

    def execute_query(self, query:str, page:int = 1, page_size:int = 25, paginate: bool = True) -> SqlQueryResponse:
        """Executes the sql query, with included
        permissions

        Args:
            query (str): the sql query
        """
        normalized_query = query.strip()
        resolver = UserParameterResolver(self.user, self.policy_manager)
        normalized_query = resolver.resolve(normalized_query) # TODO: This might interfere with queries made in a workspace
        
        if not normalized_query:
            raise ValueError("No SQL query provided")

        if not self.is_safe(normalized_query):
            raise ValueError("Only safe read-only SELECT/WITH queries are allowed")

        query_params: tuple[Any, ...] = ()
        if self.user is not None:
            compiled_query = self.policy_manager.get_accessible_sql_query(normalized_query)
            normalized_query = compiled_query.query
            query_params = compiled_query.params
        
        executor = SqlQueryExecutor()
        query_without_semicolon = normalized_query.rstrip(";")
        started_at = time.perf_counter()

        if paginate:
            normalized_page_size = max(1, min(page_size, 200))
            normalized_page = max(1, page)
            offset = (normalized_page - 1) * normalized_page_size

            count_query = (
                "SELECT COUNT(*) AS total_count "
                f"FROM ({query_without_semicolon}) AS bloomerp_sql_count_subquery"
            )
            count_result = executor.execute_to_dict(
                count_query,
                params=query_params,
                safe=True,
                use_cache=False,
            )
            count_rows = count_result.get("rows", [])
            total_row_count = int(count_rows[0][0] or 0) if count_rows else 0

            if total_row_count > 0 and offset >= total_row_count:
                normalized_page = ((total_row_count - 1) // normalized_page_size) + 1
                offset = (normalized_page - 1) * normalized_page_size

            execution_query = (
                "SELECT * "
                f"FROM ({query_without_semicolon}) AS bloomerp_sql_page_subquery "
                f"LIMIT {normalized_page_size} OFFSET {offset}"
            )
        else:
            normalized_page_size = max(1, page_size)
            normalized_page = 1
            offset = 0
            total_row_count = 0
            execution_query = query_without_semicolon

        
        result = executor.execute_to_dict(
            execution_query,
            params=query_params,
            safe=True,
            use_cache=False,
        )
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)

        columns = result.get("columns", [])
        raw_rows = result.get("rows", [])
        rows = [dict(zip(columns, row)) for row in raw_rows]
        page_rows_count = len(rows)
        if not paginate:
            total_row_count = page_rows_count
        total_pages = max(1, (total_row_count + normalized_page_size - 1) // normalized_page_size)
        page_start = offset + 1 if total_row_count > 0 else 0
        page_end = min(offset + page_rows_count, total_row_count)

        policy_message = None
        if self.user is not None and not self.user.is_superuser:
            policy_message = (
                "Results are limited by table, row, and field policies for your user."
            )

        return SqlQueryResponse(
            columns=columns,
            rows=rows,
            row_count=total_row_count,
            page_rows_count=page_rows_count,
            execution_ms=elapsed_ms,
            policy_message=policy_message,
            page=normalized_page,
            page_size=normalized_page_size,
            total_pages=total_pages,
            page_start=page_start,
            page_end=page_end,
            output_fields=DatabaseTable(
                name=query,
                fields=[
                    self._build_output_field(field, rows)
                    for field in result.get("output_fields", [])
                ],
            ),
        )
        
    def is_safe(self, query:str) -> bool:
        """Checks whether a query is deemed to be safe.
        A safe query is a read only operation.
        It does not execute the query however.

        Args:
            query (str): the sql query

        Returns:
            bool: whether it's a safe query.
        """
        if not query or not query.strip():
            return False

        cleaned = query.strip().rstrip(";").strip()
        lowered = cleaned.lower()

        if not (lowered.startswith("select") or lowered.startswith("with")):
            return False

        if ";" in cleaned:
            return False

        disallowed = re.search(
            r"\b(update|delete|insert|drop|alter|create|grant|revoke|truncate|vacuum|attach|detach|replace|upsert)\b",
            lowered,
        )

        return disallowed is None

    def _field_icon(self, field_type: str | None) -> str:
        """Returns the icon that corresponds to the primitive analytics field type."""

        return get_primitive_field_icon(field_type)

    def _build_output_field(self, field: dict[str, str], rows: list[dict[str, Any]]) -> Field:
        field_type = self._resolve_output_field_type(field["name"], field.get("field_type"), rows)
        return Field(
            name=field["name"],
            field_type=field_type,
            icon=self._field_icon(field_type),
            permissions=[],
        )

    def _resolve_output_field_type(self, field_name: str, field_type: str | None, rows: list[dict[str, Any]]) -> str:
        if field_type and field_type != "unknown":
            return to_primitive_field_type(field_type).value.key

        sampled_field_type = self._resolve_output_field_type_from_rows(field_name, rows)
        if sampled_field_type:
            return sampled_field_type

        return TileFieldType.TEXT.value.key

    def _resolve_output_field_type_from_rows(self, field_name: str, rows: list[dict[str, Any]]) -> str | None:
        for row in rows:
            value = row.get(field_name)
            if value is None:
                continue

            value_type = type(value).__name__.lower()
            if value_type in {"int", "float", "decimal"}:
                return TileFieldType.NUMERIC.value.key
            if value_type == "str":
                return TileFieldType.TEXT.value.key
            if value_type == "bool":
                return TileFieldType.BOOL.value.key
            if value_type == "date":
                return TileFieldType.DATE.value.key
            if value_type in {"datetime", "timestamp"}:
                return TileFieldType.DATETIME.value.key

            return to_primitive_field_type(value_type).value.key

        return None
