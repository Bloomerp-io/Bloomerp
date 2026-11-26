"""Searchable object references and adapters for tool-created records."""

import json
from datetime import date, time, timedelta
from decimal import Decimal
from uuid import UUID

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.http import HttpRequest
from pydantic import Field

from bloomerp.agents.definition import (
    AIArtifactCandidate,
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactRenderer,
    AIArtifactSearchPage,
    AIArtifactSearchRequest,
    AIArtifactToolResult,
    AIArtifactToolResultAdapter,
    AIArtifactTypeDefinition,
)
from bloomerp.models.definition import get_model_config
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.search_services import SearchManager


class ObjectArtifactPayload(AIArtifactPayload):
    """Identify a object source without copying its live content or permissions."""

    model_label: str = Field(
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$"
    )
    object_id: str = Field(min_length=1, max_length=255)
    object_name: str | None = Field(default=None, min_length=1, max_length=500)


def object_prompt_context(payload: ObjectArtifactPayload, request: HttpRequest) -> str:
    """Resolve current readable scalar fields for an object explicitly attached to a prompt."""
    from bloomerp.views.mcp.authoring_references import sensitive_name

    permissions = UserPolicyManager(request.user)
    obj = _readable_object(payload, permissions)
    readable = set(
        permissions.get_accessible_fields_for_object(
            obj, BloomerpPermission.VIEW
        ).values_list("field", flat=True)
    )
    config = get_model_config(obj)
    settings = config.detail_view_settings if config else None
    layout = settings.get_default_layout() if settings else None
    if layout:
        readable.intersection_update(
            item.id for row in layout.rows for item in row.items if item.is_visible
        )

    fields: dict[str, str] = {}
    for field in obj._meta.concrete_fields:
        if (
            field.name not in readable
            or not field.editable
            or field.is_relation
            or field.primary_key
            or sensitive_name(field.name)
            or field.name in getattr(obj, "SECRET_FIELDS", ())
        ):
            continue
        value = field.value_from_object(obj)
        if (
            isinstance(
                value, (str, bool, int, float, Decimal, date, time, timedelta, UUID)
            )
            and value != ""
        ):
            fields[field.name] = str(value)[:320]
        if len(fields) == 10:
            break

    live_payload = payload.model_copy(
        update={"object_name": str(obj)[:500] or str(obj.pk)}
    )
    description = describe_object(live_payload)
    return f"{description.title}. {description.summary}\nReadable record data: {json.dumps(fields, ensure_ascii=False)}"


def describe_object(payload: ObjectArtifactPayload) -> AIArtifactDescription:
    """Describe configured API availability without fetching content or granting access."""
    from bloomerp.views.api.mutations import resolve_assistant_model

    if resolve_assistant_model(payload.model_label) is None:
        availability = (
            "Generated API retrieval and mutations are unavailable for this model. "
            "Do not use api_assistant_object_retrieve or api_assistant_mutations "
            "for this reference; use another authorized tool if available."
        )
    else:
        availability = (
            "Generated API retrieval and mutations are available for this model. "
            "Use api_assistant_object_retrieve to read current permitted fields. "
            "Check api_assistant_mutation_catalog for authorized operations and "
            "writable fields before using api_assistant_mutations. "
            "API availability does not grant user, row, or field permissions."
        )
    return AIArtifactDescription(
        title=f"{payload.object_name or payload.object_id} | {payload.model_label}",
        summary=f"Reference to a record with id '{payload.object_id}'. {availability}",
    )


def _readable_object(
    payload: ObjectArtifactPayload, permissions: UserPolicyManager
) -> models.Model:
    """Load an object through the existing view permission queryset."""
    model = apps.get_model(payload.model_label)
    try:
        obj = (
            permissions.get_accessible_queryset(model, BloomerpPermission.VIEW)
            .filter(pk=payload.object_id)
            .first()
        )
    except (ValidationError, ValueError, TypeError, OverflowError) as error:
        raise PermissionDenied("Object unavailable") from error
    if obj is None or not permissions.has_global_permission(
        model, BloomerpPermission.VIEW
    ):
        raise PermissionDenied("Object unavailable")
    return obj


def authorize_object(payload: ObjectArtifactPayload, request: HttpRequest) -> None:
    """Recheck view access before signing, attaching, or rendering a record."""
    _readable_object(payload, UserPolicyManager(request.user))


class ObjectArtifactRenderer(AIArtifactRenderer[ObjectArtifactPayload]):
    """Render a conservative record link without exposing display fields via __str__."""

    @classmethod
    def render(
        cls, artifact_id: UUID, payload: ObjectArtifactPayload, request: HttpRequest
    ) -> str:
        """Check current access and use the model's registered detail URL when available."""
        from django.apps import apps
        from django.urls import NoReverseMatch, reverse
        from django.utils.html import format_html

        from bloomerp.utils.models import get_detail_view_url

        authorize_object(payload, request)
        title = describe_object(payload).title
        model = apps.get_model(payload.model_label)
        try:
            url = reverse(get_detail_view_url(model), kwargs={"pk": payload.object_id})
        except (NoReverseMatch, ValueError, AttributeError):
            return format_html(
                '<div class="badge badge-secondary">{}</div>', title
            )
        return format_html(
            '<a class="badge badge-secondary" href="{}">{} ↗</a>',
            url,
            title,
        )


class CreatedObjectAdapter(AIArtifactToolResultAdapter):
    """Attach readable records created by the existing generated-API mutation tool."""

    key = "created_object"
    tool_names = ("api_assistant_mutations",)

    @classmethod
    def adapt(
        cls, result: AIArtifactToolResult, request: HttpRequest
    ) -> list[AIArtifactCandidate]:
        """Attach matching created objects using their shared model-label identity."""
        from bloomerp.utils.api import ApiAccessResolver
        from bloomerp.views.api.mutations import resolve_assistant_model

        body = result.result.get("structuredContent")
        if result.result.get("isError") or not isinstance(body, dict):
            return []
        if (
            result.arguments.get("operation") != "create"
            or body.get("operation") != "create"
        ):
            return []
        model_label = result.arguments.get("model_label")
        returned_label = body.get("model_label")
        if not isinstance(model_label, str) or not isinstance(returned_label, str):
            return []
        model = resolve_assistant_model(model_label)
        if model is None or resolve_assistant_model(returned_label) is not model:
            return []
        record = body.get("object")
        if not isinstance(record, dict):
            return []
        object_id = record.get(model._meta.pk.name)
        if isinstance(object_id, bool) or not isinstance(object_id, (str, int)):
            return []
        resolver = ApiAccessResolver(request)
        if not resolver.get_queryset(model, "retrieve").filter(pk=object_id).exists():
            return []
        readable_fields = resolver.get_accessible_field_names(model, "retrieve")
        object_name = record.get("name")
        if (
            not isinstance(object_name, str)
            or not object_name.strip()
            or (readable_fields is not None and "name" not in readable_fields)
        ):
            object_name = f"{model._meta.verbose_name} / {object_id}"
        payload = ObjectArtifactPayload(
            model_label=model._meta.label,
            object_id=str(object_id),
            object_name=object_name[:500],
        )
        return [
            AIArtifactCandidate(
                key=f"{model._meta.label}:{object_id}",
                payload=payload.model_dump(mode="json"),
            )
        ]


def search_objects(
    request: HttpRequest, search: AIArtifactSearchRequest
) -> AIArtifactSearchPage[ObjectArtifactPayload]:
    """Adapt the shared bounded object search into attachable record references."""
    result = SearchManager(request.user).search_objects(
        query=search.query,
        per_model_limit=5,
        total_limit=search.limit,
    )
    return AIArtifactSearchPage(
        items=[
            ObjectArtifactPayload(
                model_label=type(obj)._meta.label, 
                object_id=str(obj.pk),
                object_name=obj.__str__()
            )
            for obj in result.items
        ]
    )


OBJECT_ARTIFACT = AIArtifactTypeDefinition[ObjectArtifactPayload](
    key="object",
    label="Object",
    model=ObjectArtifactPayload,
    describe=describe_object,
    authorize=authorize_object,
    render_cls=ObjectArtifactRenderer,
    search=search_objects,
    icon="fa-cube",
    tool_result_adapters=(CreatedObjectAdapter,),
)
