from django.http import HttpRequest

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.services.sql_services import DatabaseTable, SqlExecutor
from bloomerp.views.api.base import BaseBloomerpApiView
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response


class AccessibleTablesQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=25,
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    refresh = serializers.BooleanField(required=False, default=False)

    def validate_search(self, value: str) -> str:
        """Normalize table and field search terms."""
        return value.strip().lower()


class AccessibleTablesResponseSerializer(serializers.Serializer):
    databases = serializers.ListField(child=serializers.DictField())
    refreshed = serializers.BooleanField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_tables = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()


@router.register(
    path="sql/accessible-tables/",
    name="api_sql_accessible_tables",
    route_type="api",
    mcp=McpTool(
        title="List Accessible SQL Tables",
        description=(
            "List the SQL tables and fields accessible to the current user, "
            "with optional search and pagination."
        ),
        input_schema=serializer_input_schema(AccessibleTablesQuerySerializer),
        output_schema=serializer_output_schema(AccessibleTablesResponseSerializer),
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
class AccessibleTablesView(BaseBloomerpApiView):
    serializer_class = AccessibleTablesQuerySerializer
    http_method_names = ["get", "options"]

    @extend_schema(
        parameters=[AccessibleTablesQuerySerializer],
        responses={200: AccessibleTablesResponseSerializer},
        description=(
            "List SQL tables and fields available to the authenticated user. "
            "Results can be searched by table name, field name, or field type and "
            "are paginated after access policies and search filters are applied."
        ),
    )
    def get(self, request: HttpRequest, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        page = serializer.validated_data["page"]
        page_size = serializer.validated_data["page_size"]
        search = serializer.validated_data.get("search", "")
        refresh = serializer.validated_data["refresh"]

        executor = SqlExecutor(request.user)
        tables = sorted(
            executor.get_accessible_tables_and_fields(),
            key=lambda table: table.name.lower(),
        )

        if search:
            tables = _filter_tables_by_search(tables, search)

        total_tables = len(tables)
        total_pages = (total_tables + page_size - 1) // page_size
        page_start = (page - 1) * page_size
        page_tables = tables[page_start : page_start + page_size]

        response = {
            "databases": [
                {
                    "name": "bloomerp",
                    "tables": [
                        table.model_dump(include_field_icons=False) for table in page_tables
                    ],
                }
            ],
            "refreshed": refresh,
            "page": page,
            "page_size": page_size,
            "total_tables": total_tables,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1 and total_tables > 0,
        }
        return Response(response)

    def get_serializer(self, *args, **kwargs):
        return self.serializer_class(*args, **kwargs)


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
