"""SQL discovery memory hooks owned by the accessible-tables endpoint."""

from django.http import HttpRequest

from bloomerp.mcp.memory import McpMemoryPolicy, MemoryPayload, MemoryRecords
from bloomerp.services.sql_services import SqlExecutor

CONTEXT_PREFIX = (
    "Previously discovered SQL schema for this conversation (partial, not exhaustive). "
    "Reuse these canonical model labels instead of guessing them from SQL table names. "
    "Fields are discovery names/types, not a guarantee that every field is a SQL column. "
    "Discover additional fields/tables only when needed. Current SQL visibility was "
    "rechecked; mutation access and writable fields still require the mutation catalog.\n"
)


def extract_schema(result: MemoryPayload) -> MemoryRecords:
    """Keep table identities and observed fields, excluding rows and UI metadata."""
    records: MemoryRecords = {}
    payload = result.get("structuredContent", {})
    for database in payload.get("databases", []):
        if database.get("name") != "bloomerp":
            continue
        for table in database.get("tables", []):
            records[table["name"]] = {
                "table": table["name"],
                "model_label": table.get("model_label"),
                "fields": {
                    field["name"]: field["field_type"]
                    for field in table.get("fields", [])
                },
            }
    return records


def merge_schema(previous: MemoryPayload, current: MemoryPayload) -> MemoryPayload:
    """Union partial field searches while preferring current metadata."""
    return {
        **current,
        "fields": {**previous.get("fields", {}), **current.get("fields", {})},
    }


def validate_schema(request: HttpRequest, records: MemoryRecords) -> MemoryRecords:
    """Remove revoked fields and refresh canonical labels through current SQL access."""
    accessible = {
        table.name: table
        for table in SqlExecutor(request.user).get_accessible_tables_and_fields()
    }
    validated: MemoryRecords = {}
    for key, record in records.items():
        table = accessible.get(key)
        if table is None:
            continue
        fields = {
            field.name: field.field_type
            for field in table.fields
            if field.name in record.get("fields", {})
        }
        if fields:
            validated[key] = {
                "table": key,
                "model_label": table.model_label,
                "fields": fields,
            }
    return validated


SQL_DISCOVERY_MEMORY = McpMemoryPolicy(
    extract=extract_schema,
    merge=merge_schema,
    validate=validate_schema,
    context_prefix=CONTEXT_PREFIX,
)
