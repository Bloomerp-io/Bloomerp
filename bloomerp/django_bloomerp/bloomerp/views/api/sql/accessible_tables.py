from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from bloomerp.router import router
from bloomerp.services.sql_services import DatabaseTable, SqlExecutor


@router.register(path="api/sql/accessible-tables/", name="api_sql_accessible_tables")
@login_required
def accessible_tables(request: HttpRequest) -> JsonResponse:
    search = request.GET.get("search", "").strip().lower()
    refresh = request.GET.get("refresh", "false").lower() == "true"

    executor = SqlExecutor(request.user)
    tables = executor.get_accessible_tables_and_fields()

    if search:
        tables = _filter_tables_by_search(tables, search)

    response = {
        "databases": [
            {
                "name": "bloomerp",
                "icon": "fa-solid fa-database",
                "tables": [table.model_dump() for table in tables],
            }
        ],
        "refreshed": refresh,
    }

    return JsonResponse(response)


def _filter_tables_by_search(tables: list[DatabaseTable], search: str) -> list[DatabaseTable]:
    filtered_tables: list[DatabaseTable] = []

    for table in tables:
        table_match = search in table.name.lower()
        matching_fields = [
            field
            for field in table.fields
            if search in field.name.lower() or search in field.field_type.lower()
        ]

        if table_match:
            filtered_tables.append(table)
            continue

        if matching_fields:
            filtered_tables.append(
                DatabaseTable(
                    name=table.name,
                    icon=table.icon,
                    content_type_id=table.content_type_id,
                    fields=matching_fields,
                )
            )

    return filtered_tables
