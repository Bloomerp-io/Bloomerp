from django.http import HttpRequest

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.views.api.base import BaseBloomerpApiView
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


class ExecuteSqlRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The SQL query to execute.",
        style={"base_template": "textarea.html"},
    )
    page = serializers.IntegerField(
        required=False,
        min_value=1,
        default=1,
        help_text="The page number for paginated results.",
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        default=25,
        help_text="The number of rows per page.",
    )

    def to_internal_value(self, data):
        data = data.copy()
        for field_name in ("page", "page_size"):
            if data.get(field_name) in ("", None):
                data.pop(field_name, None)
        return super().to_internal_value(data)

    def validate(self, attrs):
        query = (attrs.get("query") or "").strip()
        if not query:
            raise serializers.ValidationError({"query": "No SQL query provided"})

        attrs["query"] = query
        return attrs


class ExecuteSqlResponseSerializer(serializers.Serializer):
    columns = serializers.ListField(child=serializers.CharField())
    rows = serializers.ListField(child=serializers.DictField())
    row_count = serializers.IntegerField()
    page_rows_count = serializers.IntegerField()
    execution_ms = serializers.IntegerField()
    policy_message = serializers.CharField(allow_null=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    page_start = serializers.IntegerField()
    page_end = serializers.IntegerField()
    output_fields = serializers.DictField(allow_null=True)


class ExecuteSqlErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField()


@router.register(
    path="sql/execute/",
    route_type="api",
    name="Execute SQL",
    url_name="api_sql_execute",
    mcp=McpTool(
        title="Execute SQL",
        description="Execute a permission-filtered read-only SQL query.",
        input_schema=lambda: serializer_input_schema(ExecuteSqlRequestSerializer),
        output_schema=lambda: serializer_output_schema(ExecuteSqlResponseSerializer),
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
class ExecuteSqlView(BaseBloomerpApiView):
    serializer_class = ExecuteSqlRequestSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ["post", "options"]

    @extend_schema(
        request=ExecuteSqlRequestSerializer,
        responses={
            200: ExecuteSqlResponseSerializer,
            400: ExecuteSqlErrorResponseSerializer,
            403: ExecuteSqlErrorResponseSerializer,
            500: ExecuteSqlErrorResponseSerializer,
        },
        description="Execute a SQL query and return the results in JSON format.",
    )
    def post(self, request: HttpRequest, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not getattr(request.user, "is_staff", False):
            return Response(
                {"error": "You do not have permission to execute SQL queries."},
                status=403,
            )
        
        
        query = serializer.validated_data["query"]
        page = serializer.validated_data["page"]
        page_size = serializer.validated_data["page_size"]
        executor = SqlExecutor(request.user)

        try:
            result = executor.execute_query(query, page=page, page_size=page_size)
        except PermissionError as error:
            return Response({"error": str(error)}, status=403)
        except ValueError as error:
            return Response({"error": str(error)}, status=400)
        except Exception as error:
            return Response({"error": f"Query execution failed: {error}"}, status=500)

        return Response(
            {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "page_rows_count": result.page_rows_count,
                "execution_ms": result.execution_ms,
                "policy_message": result.policy_message,
                "page": result.page,
                "page_size": result.page_size,
                "total_pages": result.total_pages,
                "page_start": result.page_start,
                "page_end": result.page_end,
                "output_fields": (
                    result.output_fields.model_dump(include_field_icons=False)
                    if result.output_fields
                    else None
                ),
            }
        )

    def get_serializer(self, *args, **kwargs):
        return self.serializer_class(*args, **kwargs)
