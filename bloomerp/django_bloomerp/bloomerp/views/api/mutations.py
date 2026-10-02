from __future__ import annotations

from collections.abc import Mapping
from copy import copy

from django.core.exceptions import FieldDoesNotExist
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.utils.api import ApiAccessResolver
from bloomerp.utils.models import model_name_plural_underline
from bloomerp.views.api.base import BaseBloomerpApiView
from bloomerp.views.api.generic.base import BaseModelApiView, get_auto_api_models


class AssistantMutationRequestSerializer(serializers.Serializer):
    resource = serializers.CharField(
        help_text="The generated API resource key, for example `customers`.",
    )
    operation = serializers.ChoiceField(
        choices=("create", "update", "delete"),
        help_text="`update` applies a partial update to the target object.",
    )
    object_id = serializers.CharField(
        required=False,
        help_text="The target object's primary key. Required for `update` and `delete`.",
    )
    data = serializers.JSONField(
        required=False,
        help_text="An object containing the model fields to create or update.",
    )

    def validate_resource(self, value: str) -> str:
        resource = value.strip().strip("/")
        if not resource:
            raise serializers.ValidationError("This field may not be blank.")
        return resource

    def validate(self, attrs: dict) -> dict:
        operation = attrs["operation"]
        object_id = attrs.get("object_id")
        data = attrs.get("data")

        if operation == "create":
            if object_id:
                raise serializers.ValidationError(
                    {"object_id": "Do not provide object_id when creating an object."}
                )
        elif not object_id:
            raise serializers.ValidationError(
                {"object_id": "This field is required for update and delete operations."}
            )

        if operation in {"create", "update"}:
            if data is None:
                raise serializers.ValidationError(
                    {"data": "This field is required for create and update operations."}
                )
            if not isinstance(data, Mapping):
                raise serializers.ValidationError(
                    {"data": "Expected an object keyed by model field names."}
                )
        elif data is not None:
            raise serializers.ValidationError(
                {"data": "Do not provide data when deleting an object."}
            )

        return attrs


class AssistantMutationResponseSerializer(serializers.Serializer):
    resource = serializers.CharField()
    operation = serializers.ChoiceField(choices=("create", "update", "delete"))
    object = serializers.DictField(required=False)
    object_id = serializers.CharField(required=False)


class AssistantMutationCatalogResponseSerializer(serializers.Serializer):
    resources = serializers.ListField(child=serializers.DictField())
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_resources = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()


class AssistantMutationCatalogQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=50, default=10)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    resource = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_search(self, value: str) -> str:
        return value.strip()

    def validate_resource(self, value: str) -> str:
        return value.strip().strip("/")


@router.register(
    path="mutations/catalog/",
    route_type="api",
    name="Assistant Mutation Catalog",
    url_name="api_assistant_mutation_catalog",
    mcp=McpTool(
        title="List available mutations",
        description=(
            "List generated API resources, operations, and writable fields available "
            "to the authenticated user."
        ),
        input_schema=lambda: serializer_input_schema(
            AssistantMutationCatalogQuerySerializer
        ),
        output_schema=lambda: serializer_output_schema(
            AssistantMutationCatalogResponseSerializer
        ),
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
class AssistantMutationCatalogView(BaseBloomerpApiView):
    """List generated API resources and writable fields for assistant mutations."""

    _SYSTEM_MANAGED_FIELD_NAMES = frozenset({"created_by", "updated_by"})

    permission_classes = (IsAuthenticated,)
    http_method_names = ["get", "options"]

    @extend_schema(
        tags=["Assistant"],
        parameters=[
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Page number, starting at 1.",
            ),
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Resources per page. Defaults to 10 and may not exceed 50.",
            ),
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Case-insensitive search across resource keys, model names, and labels.",
            ),
            OpenApiParameter(
                name="resource",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Exact resource key, for example customers.",
            ),
        ],
        responses={200: AssistantMutationCatalogResponseSerializer},
        description=(
            "List generated API resources, operations, and writable API fields available "
            "to the authenticated user. Results are paginated and can be filtered with "
            "search or an exact resource key. Use returned resource and field names with "
            "the Assistant Mutations endpoint."
        ),
    )
    def get(self, request: HttpRequest, *args, **kwargs) -> Response:
        query_serializer = AssistantMutationCatalogQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        page = query_serializer.validated_data["page"]
        page_size = query_serializer.validated_data["page_size"]
        search = query_serializer.validated_data.get("search", "").lower()
        resource_filter = query_serializer.validated_data.get("resource", "")
        resolver = ApiAccessResolver(request)
        models = [
            model
            for model in sorted(get_auto_api_models(), key=self._resource_key)
            if self._has_mutation_access(resolver, model)
            and self._matches_query(model, search, resource_filter)
        ]
        total_resources = len(models)
        total_pages = (total_resources + page_size - 1) // page_size
        page_start = (page - 1) * page_size
        page_models = models[page_start : page_start + page_size]

        resources = []
        for model in page_models:
            operations = self._get_operations(request, resolver, model)
            if operations:
                resources.append(
                    {
                        "resource": self._resource_key(model),
                        "label": str(model._meta.verbose_name_plural),
                        "object_id": self._primary_key_schema(model),
                        "operations": operations,
                    }
                )

        return Response(
            {
                "resources": resources,
                "page": page,
                "page_size": page_size,
                "total_resources": total_resources,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1 and total_resources > 0,
            }
        )

    def _has_mutation_access(self, resolver: ApiAccessResolver, model) -> bool:
        if self._has_action_access(resolver, model, "create"):
            return True
        if self._has_action_access(resolver, model, "destroy"):
            return True
        if not self._has_action_access(resolver, model, "update"):
            return False

        writable_fields = resolver.get_accessible_field_names(model, "update")
        return writable_fields is None or bool(writable_fields)

    def _matches_query(self, model, search: str, resource_filter: str) -> bool:
        resource = self._resource_key(model)
        if resource_filter and resource != resource_filter:
            return False
        if not search:
            return True

        searchable_values = (
            resource,
            model._meta.model_name,
            str(model._meta.verbose_name),
            str(model._meta.verbose_name_plural),
        )
        return any(search in value.lower() for value in searchable_values)

    def _get_operations(self, request, resolver: ApiAccessResolver, model) -> dict:
        operations = {}

        if self._has_action_access(resolver, model, "create"):
            operations["create"] = {
                "fields": self._get_writable_fields(request, resolver, model, "create"),
            }

        if self._has_action_access(resolver, model, "update"):
            fields = self._get_writable_fields(request, resolver, model, "update")
            if fields:
                operations["update"] = {
                    "object_id": self._primary_key_schema(model),
                    "fields": fields,
                }

        if self._has_action_access(resolver, model, "destroy"):
            operations["delete"] = {"object_id": self._primary_key_schema(model)}

        return operations

    def _has_action_access(self, resolver: ApiAccessResolver, model, action: str) -> bool:
        if getattr(resolver.permission_manager.user, "is_superuser", False):
            return True
        return (
            resolver.has_action_access(model, action)
        )

    def _get_writable_fields(self, request, resolver: ApiAccessResolver, model, action: str) -> list[dict]:
        allowed_fields = resolver.get_accessible_field_names(model, action)
        serializer = self._get_model_serializer(request, model, action)
        return [
            self._serialize_field(name, field, action)
            for name, field in serializer.fields.items()
            if not field.read_only
            and not self._is_system_managed_field(model, name)
            and (allowed_fields is None or name in allowed_fields)
        ]

    def _is_system_managed_field(self, model, field_name: str) -> bool:
        """Exclude fields BloomERP or Django fills in without assistant input."""
        if field_name in self._SYSTEM_MANAGED_FIELD_NAMES:
            return True

        try:
            model_field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return False

        return bool(
            getattr(model_field, "auto_now", False)
            or getattr(model_field, "auto_now_add", False)
        )

    def _get_model_serializer(self, request, model, action: str):
        viewset = BaseModelApiView()
        viewset.model = model
        viewset.request = request
        viewset.action = "partial_update" if action == "update" else action
        viewset.args = ()
        viewset.kwargs = {}
        viewset.format_kwarg = None
        return viewset.get_serializer()

    def _serialize_field(self, name: str, field, action: str) -> dict:
        field_schema = {
            "name": name,
            "type": self._field_type(field),
            "required": action == "create" and field.required,
            "allow_null": bool(getattr(field, "allow_null", False)),
        }

        field_format = self._field_format(field)
        if field_format:
            field_schema["format"] = field_format
        if field.label:
            field_schema["label"] = str(field.label)
        if field.help_text:
            field_schema["help_text"] = str(field.help_text)
        if getattr(field, "allow_blank", False):
            field_schema["allow_blank"] = True
        if getattr(field, "max_length", None) is not None:
            field_schema["max_length"] = field.max_length
        if getattr(field, "min_length", None) is not None:
            field_schema["min_length"] = field.min_length

        related_model = self._related_model(field)
        if related_model is not None:
            field_schema["related_resource"] = self._resource_key(related_model)
        else:
            choices = self._serialize_choices(field)
            if choices:
                field_schema["choices"] = choices

        return field_schema

    def _serialize_choices(self, field) -> list[dict]:
        choices = getattr(field, "choices", None)
        if not choices:
            return []

        choice_items = choices.items() if isinstance(choices, Mapping) else choices
        serialized_choices = []
        for value, label in choice_items:
            serialized_choices.append(
                {
                    "value": self._json_value(value),
                    "label": str(label),
                }
            )
        return serialized_choices

    def _field_type(self, field) -> str:
        if isinstance(field, (serializers.ManyRelatedField, serializers.ListField)):
            return "array"
        if isinstance(field, (serializers.DictField, serializers.JSONField)):
            return "object"
        if isinstance(field, serializers.BooleanField):
            return "boolean"
        if isinstance(field, serializers.IntegerField):
            return "integer"
        if isinstance(field, (serializers.FloatField, serializers.DecimalField)):
            return "number"
        if isinstance(field, serializers.PrimaryKeyRelatedField):
            related_model = self._related_model(field)
            if related_model is not None:
                return self._primary_key_schema(related_model)["type"]
        return "string"

    def _field_format(self, field) -> str | None:
        if isinstance(field, serializers.DateTimeField):
            return "date-time"
        if isinstance(field, serializers.DateField):
            return "date"
        if isinstance(field, serializers.TimeField):
            return "time"
        if isinstance(field, serializers.UUIDField):
            return "uuid"
        if isinstance(field, serializers.EmailField):
            return "email"
        if isinstance(field, serializers.URLField):
            return "uri"
        if isinstance(field, serializers.DecimalField):
            return "decimal"
        if isinstance(field, serializers.PrimaryKeyRelatedField):
            related_model = self._related_model(field)
            if related_model is not None:
                return self._primary_key_schema(related_model).get("format")
        return None

    def _related_model(self, field):
        if isinstance(field, serializers.ManyRelatedField):
            field = field.child_relation
        queryset = getattr(field, "queryset", None)
        return getattr(queryset, "model", None)

    def _primary_key_schema(self, model) -> dict:
        primary_key = model._meta.pk
        internal_type = primary_key.get_internal_type()
        schema = {"field": primary_key.name, "type": "string"}
        if internal_type in {
            "AutoField",
            "BigAutoField",
            "IntegerField",
            "BigIntegerField",
            "SmallIntegerField",
            "PositiveIntegerField",
            "PositiveSmallIntegerField",
        }:
            schema["type"] = "integer"
        elif internal_type == "UUIDField":
            schema["format"] = "uuid"
        return schema

    def _resource_key(self, model) -> str:
        return model_name_plural_underline(model)

    def _json_value(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)


@router.register(
    path="mutations/",
    route_type="api",
    name="Assistant Mutations",
    url_name="api_assistant_mutations",
    mcp=McpTool(
        title="Mutate an object",
        description=(
            "Create, update, or delete an object through Bloomerp's "
            "permission-aware generated API."
        ),
        input_schema=lambda: serializer_input_schema(
            AssistantMutationRequestSerializer
        ),
        output_schema=lambda: serializer_output_schema(
            AssistantMutationResponseSerializer
        ),
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
class AssistantMutationView(BaseBloomerpApiView):
    """Create, update, or delete one generated API object by resource key."""

    serializer_class = AssistantMutationRequestSerializer
    permission_classes = (IsAuthenticated,)
    http_method_names = ["post", "options"]

    @extend_schema(
        tags=["Assistant"],
        request=AssistantMutationRequestSerializer,
        responses={
            200: AssistantMutationResponseSerializer,
            201: AssistantMutationResponseSerializer,
            400: serializers.DictField(),
            403: serializers.DictField(),
            404: serializers.DictField(),
        },
        description=(
            "Create, partially update, or delete one object exposed by BloomERP's "
            "generated model API. The resource is resolved server-side; this endpoint "
            "does not accept arbitrary URLs or HTTP methods."
        ),
    )
    def post(self, request: HttpRequest, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        resource = serializer.validated_data["resource"]
        operation = serializer.validated_data["operation"]
        model = self._get_model_for_resource(resource)
        if model is None:
            raise ValidationError({"resource": "Unknown generated API resource."})

        response = self._perform_mutation(
            request,
            model=model,
            operation=operation,
            data=serializer.validated_data.get("data"),
            object_id=serializer.validated_data.get("object_id"),
        )

        result = {"resource": resource, "operation": operation}
        if operation == "delete":
            result["object_id"] = serializer.validated_data["object_id"]
            return Response(result, status=status.HTTP_200_OK)

        result["object"] = response.data
        return Response(result, status=response.status_code, headers=response.headers)

    def get_serializer(self, *args, **kwargs):
        return self.serializer_class(*args, **kwargs)

    def _get_model_for_resource(self, resource: str):
        for model in get_auto_api_models():
            route_resource = model_name_plural_underline(model)
            if route_resource == resource:
                return model
        return None

    def _perform_mutation(self, request, *, model, operation: str, data, object_id: str | None) -> Response:
        action = {"create": "create", "update": "partial_update", "delete": "destroy"}[operation]
        model_request = copy(request)
        model_request._full_data = data or {}

        viewset = BaseModelApiView()
        viewset.model = model
        viewset.request = model_request
        viewset.action = action
        viewset.args = ()
        viewset.kwargs = {"pk": object_id} if object_id is not None else {}
        viewset.format_kwarg = None

        if operation == "create":
            return viewset.create(model_request)
        if operation == "update":
            return viewset.partial_update(model_request)
        return viewset.destroy(model_request)
