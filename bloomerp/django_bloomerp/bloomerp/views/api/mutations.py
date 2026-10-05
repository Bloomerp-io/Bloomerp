from __future__ import annotations

from collections.abc import Mapping
from copy import copy
from typing import Any

from django.core.exceptions import (
    FieldDoesNotExist,
    ValidationError as DjangoValidationError,
)
from django.db.models import Model
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from bloomerp.utils.api import ApiAccessResolver
from bloomerp.views.api.base import BaseBloomerpApiView
from bloomerp.views.api.generic.base import BaseModelApiView, get_auto_api_models


def resolve_assistant_model(model_label: str) -> type[Model] | None:
    """Resolve only models currently exposed by the generated API, by Django label."""
    for model in get_auto_api_models():
        if model._meta.label_lower == model_label.lower():
            return model
    return None


class AssistantModelIdentitySerializer(serializers.Serializer):
    """Reject obsolete resource keys instead of silently ignoring them."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Require callers to identify models through model_label."""
        if isinstance(data, Mapping) and "resource" in data:
            raise serializers.ValidationError({"resource": "Use model_label instead of resource."})
        return super().to_internal_value(data)


class AssistantObjectRetrieveRequestSerializer(AssistantModelIdentitySerializer):
    """Accept the model label and primary key supplied by an object artifact."""

    model_label = serializers.RegexField(
        regex=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
        help_text="The object's Django model label, for example `sales.Customer`.",
    )
    object_id = serializers.CharField(
        max_length=255,
        help_text="The target object's primary key from the object artifact.",
    )


class AssistantObjectRetrieveResponseSerializer(serializers.Serializer):
    """Return permitted fields and the canonical model identity used for mutations."""

    model_label = serializers.CharField(
        help_text="Use this model_label directly in mutation calls."
    )
    object_id = serializers.CharField()
    object = serializers.DictField()


def object_retrieve_input_schema() -> dict[str, Any]:
    """Describe the artifact identity accepted by the read-only MCP tool."""
    return serializer_input_schema(AssistantObjectRetrieveRequestSerializer)


def object_retrieve_output_schema() -> dict[str, Any]:
    """Describe the retrieved object and its shared model-label identity."""
    return serializer_output_schema(AssistantObjectRetrieveResponseSerializer)


@router.register(
    path="objects/retrieve/",
    route_type="api",
    name="Assistant Object Retrieval",
    url_name="api_assistant_object_retrieve",
    mcp=McpTool(
        title="Retrieve an object",
        description=(
            "Read an object's current permitted fields using the model_label and "
            "object_id from an object artifact. Use the same model_label for mutations."
        ),
        input_schema=object_retrieve_input_schema,
        output_schema=object_retrieve_output_schema,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
class AssistantObjectRetrieveView(BaseBloomerpApiView):
    """Retrieve one generated API object directly from an artifact identity."""

    permission_classes = (IsAuthenticated,)
    http_method_names = ["get", "options"]

    @extend_schema(
        tags=["Assistant"],
        parameters=[AssistantObjectRetrieveRequestSerializer],
        responses={
            200: AssistantObjectRetrieveResponseSerializer,
            400: serializers.DictField(),
            403: serializers.DictField(),
            404: serializers.DictField(),
        },
        description=(
            "Retrieve an object exposed by the generated model API using its model "
            "label and primary key. Applies the generated API's row and field access."
        ),
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Resolve an exposed model and delegate retrieval to its generated API."""
        serializer = AssistantObjectRetrieveRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        model_label = serializer.validated_data["model_label"]
        object_id = serializer.validated_data["object_id"]
        model = self._get_model_for_label(model_label)
        if model is None:
            raise ValidationError({"model_label": "Unknown generated API model."})

        try:
            model._meta.pk.to_python(object_id)
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise ValidationError(
                {"object_id": "Invalid primary key for this model."}
            ) from exc

        viewset = BaseModelApiView()
        viewset.model = model
        viewset.request = request
        viewset.action = "retrieve"
        viewset.args = ()
        viewset.kwargs = {"pk": object_id}
        viewset.format_kwarg = None
        viewset.filter_backends = ()
        response = viewset.retrieve(request)
        return Response(
            {
                "model_label": model._meta.label,
                "object_id": object_id,
                "object": response.data,
            },
            status=response.status_code,
            headers=response.headers,
        )

    def _get_model_for_label(self, model_label: str) -> type[Model] | None:
        """Resolve only models currently exposed by the generated API."""
        return resolve_assistant_model(model_label)


class AssistantMutationRequestSerializer(AssistantModelIdentitySerializer):
    """Accept the same model label used by shared object and model artifacts."""

    model_label = serializers.RegexField(
        regex=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
        help_text="The Django model label from the artifact or catalog, for example `sales.Customer`.",
    )
    operation = serializers.ChoiceField(
        choices=("create", "update", "delete"),
        help_text="`update` applies a partial update to the target object.",
    )
    object_id = serializers.CharField(
        required=False,
        help_text="The target object's primary key. Required for `update` and `delete`.",
    )
    data = serializers.DictField(
        required=False,
        help_text=(
            "An object containing the model fields to create or update. "
            "Pass the object directly, not a JSON-encoded string."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require a model identity and the data needed by the chosen operation."""
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
                {
                    "object_id": "This field is required for update and delete operations."
                }
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
    """Return the canonical model label and the mutation outcome."""

    model_label = serializers.CharField()
    operation = serializers.ChoiceField(choices=("create", "update", "delete"))
    object = serializers.DictField(required=False)
    object_id = serializers.CharField(required=False)


class AssistantMutationCatalogEntrySerializer(serializers.Serializer):
    """Advertise canonical model identities and their authorized mutation contracts."""

    model_label = serializers.CharField(help_text="Use this model_label in retrieve and mutation calls.")
    label = serializers.CharField()
    object_id = serializers.DictField()
    operations = serializers.DictField()


class AssistantMutationCatalogResponseSerializer(serializers.Serializer):
    resources = AssistantMutationCatalogEntrySerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_resources = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()


class AssistantMutationCatalogQuerySerializer(AssistantModelIdentitySerializer):
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False, min_value=1, max_value=50, default=10
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    model_label = serializers.RegexField(
        regex=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
        required=False,
        help_text="Exact Django model label, for example `sales.Customer`.",
    )

    def validate_search(self, value: str) -> str:
        """Trim a catalog search without changing its case-insensitive semantics."""
        return value.strip()



@router.register(
    path="mutations/catalog/",
    route_type="api",
    name="Assistant Mutation Catalog",
    url_name="api_assistant_mutation_catalog",
    mcp=McpTool(
        title="List available mutations",
        description=(
            "List generated API model labels, operations, and writable fields available "
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
                description="Case-insensitive search across model labels and display names.",
            ),
            OpenApiParameter(
                name="model_label",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Exact Django model label from an artifact, for example sales.Customer.",
            ),
        ],
        responses={200: AssistantMutationCatalogResponseSerializer},
        description=(
            "List generated API resources, operations, and writable API fields available "
            "to the authenticated user. Results are paginated and can be filtered with "
            "search or an exact model_label. Use returned model_label and field names with "
            "the Assistant Mutations endpoint."
        ),
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List authorized mutation contracts identified by shared model labels."""
        query_serializer = AssistantMutationCatalogQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)

        page = query_serializer.validated_data["page"]
        page_size = query_serializer.validated_data["page_size"]
        search = query_serializer.validated_data.get("search", "").lower()
        model_filter = query_serializer.validated_data.get("model_label", "").lower()
        resolver = ApiAccessResolver(request)
        models = [
            model
            for model in sorted(get_auto_api_models(), key=self._model_label)
            if self._has_mutation_access(resolver, model)
            and (not model_filter or model._meta.label_lower == model_filter)
            and self._matches_query(model, search)
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
                        "model_label": model._meta.label,
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

    def _matches_query(self, model: type[Model], search: str) -> bool:
        """Search canonical model labels and human-readable model names."""
        if not search:
            return True

        searchable_values = (
            model._meta.label,
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

    def _serialize_field(
        self, name: str, field: serializers.Field, action: str
    ) -> dict[str, Any]:
        """Describe a writable field with canonical identities for related models."""
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
            field_schema["related_model_label"] = related_model._meta.label
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

    def _model_label(self, model: type[Model]) -> str:
        """Return the canonical model identity used to sort catalog entries."""
        return model._meta.label

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
            "permission-aware generated API using the model_label from an artifact or catalog."
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
    """Mutate a generated API object using its shared model-label identity."""

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
            "generated model API. The model_label is resolved server-side; this endpoint "
            "does not accept arbitrary URLs or HTTP methods."
        ),
    )
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Resolve a shared model identity and delegate to its permission-aware API."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        model_label = serializer.validated_data["model_label"]
        operation = serializer.validated_data["operation"]
        model = resolve_assistant_model(model_label)
        if model is None:
            raise ValidationError({"model_label": "Unknown generated API model."})

        response = self._perform_mutation(
            request,
            model=model,
            operation=operation,
            data=serializer.validated_data.get("data"),
            object_id=serializer.validated_data.get("object_id"),
        )

        result = {
            "model_label": model._meta.label,
            "operation": operation,
        }
        if operation == "delete":
            result["object_id"] = serializer.validated_data["object_id"]
            return Response(result, status=status.HTTP_200_OK)

        result["object"] = response.data
        return Response(result, status=response.status_code, headers=response.headers)

    def get_serializer(
        self, *args: Any, **kwargs: Any
    ) -> AssistantMutationRequestSerializer:
        """Build the assistant mutation request serializer."""
        return self.serializer_class(*args, **kwargs)

    def _perform_mutation(
        self,
        request: Request,
        *,
        model: type[Model],
        operation: str,
        data: Mapping[str, Any] | None,
        object_id: str | None,
    ) -> Response:
        """Execute the selected operation with the generated API's access enforcement."""
        action = {"create": "create", "update": "partial_update", "delete": "destroy"}[
            operation
        ]
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
