import re
import time
from typing import Any

from bloomerp.models import ApplicationField
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.sql import SqlQueryExecutor
from pydantic import BaseModel

class Field(BaseModel):
    name:str
    field_type:str
    icon:str = "fa-solid fa-table-columns"
    permissions:list[str] = []

class DatabaseTable(BaseModel):
    name:str
    icon:str = "fa-solid fa-table"
    content_type_id:int | None = None
    fields:list[Field]


class SqlQueryResponse(BaseModel):
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
    

class SqlExecutor:
    """
    Class for executing SQL query within the app.
    """
    def __init__(self, user: AbstractBloomerpUser | None = None):
        self.user = user
        self.permission_manager = UserPermissionManager(user) if user is not None else None
        
     
    def get_accessible_tables_and_fields(self) -> list[DatabaseTable]:
        """Returns the accessible tables and fields for 
        the user.

        Returns:
            list[DatabaseTable]: list of database tables with fields
        """
        if self.user is None or self.permission_manager is None:
            return []

        content_types = self.user.get_content_types_for_user(permission_types=["view"])
        if not content_types.exists():
            return []

        tables: dict[str, DatabaseTable] = {}

        for content_type in content_types:
            model_cls = content_type.model_class()
            if not model_cls:
                continue

            permission_str = create_permission_str(model_cls, "view")
            accessible_fields_qs = self.permission_manager.get_accessible_fields(content_type, permission_str)
            accessible_field_ids = set(accessible_fields_qs.values_list("id", flat=True))

            app_fields = ApplicationField.objects.filter(
                content_type=content_type,
                db_table__isnull=False,
                db_column__isnull=False,
            ).exclude(db_table="").exclude(db_column="")

            if not self.user.is_superuser:
                app_fields = app_fields.filter(id__in=accessible_field_ids)

            if not app_fields.exists():
                continue

            for app_field in app_fields:
                table_name = app_field.db_table
                if table_name not in tables:
                    tables[table_name] = DatabaseTable(
                        name=table_name,
                        content_type_id=content_type.id,
                        fields=[],
                    )

                tables[table_name].fields.append(
                    Field(
                        name=app_field.db_column,
                        field_type=app_field.db_field_type or app_field.field_type,
                        icon=self._field_icon(app_field.field_type),
                        permissions=[permission_str],
                    )
                )

        for table in tables.values():
            table.fields = sorted(table.fields, key=lambda field: field.name.lower())

        return sorted(tables.values(), key=lambda table: table.name.lower())
    

    def execute_query(self, query:str, page:int = 1, page_size:int = 25) -> SqlQueryResponse:
        """Executes the sql query, with included
        permissions

        Args:
            query (str): the sql query
        """
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError("No SQL query provided")

        if not self.is_safe(normalized_query):
            raise ValueError("Only safe read-only SELECT/WITH queries are allowed")

        if self.user is not None:
            allowed_tables = {table.name for table in self.get_accessible_tables_and_fields()}
            referenced_tables = self._extract_referenced_tables(normalized_query)
            blocked_tables = [
                table_name
                for table_name in referenced_tables
                if table_name not in allowed_tables and table_name.split(".")[-1] not in allowed_tables
            ]

            if blocked_tables:
                blocked_list = ", ".join(sorted(set(blocked_tables)))
                raise PermissionError(f"You do not have access to table(s): {blocked_list}")

        normalized_page_size = max(1, min(page_size, 200))
        normalized_page = max(1, page)
        offset = (normalized_page - 1) * normalized_page_size

        executor = SqlQueryExecutor()
        query_without_semicolon = normalized_query.rstrip(";")
        count_query = (
            "SELECT COUNT(*) AS total_count "
            f"FROM ({query_without_semicolon}) AS bloomerp_sql_count_subquery"
        )

        started_at = time.perf_counter()
        count_result = executor.execute_to_dict(count_query, safe=True, use_cache=False)
        count_rows = count_result.get("rows", [])
        total_row_count = int(count_rows[0][0] or 0) if count_rows else 0

        if total_row_count > 0 and offset >= total_row_count:
            normalized_page = ((total_row_count - 1) // normalized_page_size) + 1
            offset = (normalized_page - 1) * normalized_page_size

        paginated_query = (
            "SELECT * "
            f"FROM ({query_without_semicolon}) AS bloomerp_sql_page_subquery "
            f"LIMIT {normalized_page_size} OFFSET {offset}"
        )

        result = executor.execute_to_dict(paginated_query, safe=True, use_cache=False)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)

        columns = result.get("columns", [])
        raw_rows = result.get("rows", [])
        rows = [dict(zip(columns, row)) for row in raw_rows]
        page_rows_count = len(rows)
        total_pages = max(1, (total_row_count + normalized_page_size - 1) // normalized_page_size)
        page_start = offset + 1 if total_row_count > 0 else 0
        page_end = min(offset + page_rows_count, total_row_count)

        policy_message = None
        if self.user is not None and not self.user.is_superuser:
            policy_message = (
                "Results are limited to accessible tables and fields for your user. "
                "Row policies are enforced in ORM views and may further restrict accessible records."
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

    
    def _extract_referenced_tables(self, query: str) -> set[str]:
        matches = re.findall(r"\b(?:from|join)\s+([\w\.\"]+)", query, flags=re.IGNORECASE)
        normalized_tables: set[str] = set()

        for match in matches:
            table_name = match.strip().strip('"')
            if table_name:
                normalized_tables.add(table_name)

        return normalized_tables

    def _field_icon(self, field_type: str | None) -> str:
        normalized = (field_type or "").lower()

        if "int" in normalized or "decimal" in normalized or "float" in normalized:
            return "fa-solid fa-hashtag"

        if "date" in normalized or "time" in normalized:
            return "fa-solid fa-calendar-days"

        if "bool" in normalized:
            return "fa-solid fa-toggle-on"

        if "foreign" in normalized or "one" in normalized or "many" in normalized:
            return "fa-solid fa-link"

        return "fa-solid fa-table-columns"
