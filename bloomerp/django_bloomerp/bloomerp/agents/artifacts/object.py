"""Searchable object references and adapters for tool-created records."""

from uuid import UUID

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
from bloomerp.services.search_services import SearchManager


class ObjectArtifactPayload(AIArtifactPayload):
    """Identify a object source without copying its live content or permissions."""

    model_label: str = Field(
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$"
    )
    object_id: str = Field(min_length=1, max_length=255)
    object_name:str = Field(min_length=1, max_length=500)


def describe_object(payload: ObjectArtifactPayload) -> AIArtifactDescription:
    """Describe the reference without fetching content or asserting target access."""
    return AIArtifactDescription(
        title=f"{payload.object_name} | {payload.model_label}",
        summary=f"Reference to a record with id '{payload.object_id}'; read its current permitted fields through an available tool.",
    )


def authorize_object(payload: ObjectArtifactPayload, request: HttpRequest) -> None:
    """Recheck the shared row-level view permission without exposing display fields."""
    from django.apps import apps
    from django.core.exceptions import PermissionDenied

    from bloomerp.permissions.definition import BloomerpPermission
    from bloomerp.permissions.manager import UserPolicyManager

    model = apps.get_model(payload.model_label)
    if (
        model is None
        or not UserPolicyManager(request.user)
        .get_accessible_queryset(model, BloomerpPermission.VIEW)
        .filter(pk=payload.object_id)
        .exists()
    ):
        raise PermissionDenied("Object unavailable")


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
