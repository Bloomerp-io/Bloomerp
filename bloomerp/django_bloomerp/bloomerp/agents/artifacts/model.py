"""Searchable model references using the shared policy-aware model discovery."""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from pydantic import Field

from bloomerp.agents.definition import (
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactSearchPage,
    AIArtifactSearchRequest,
    AIArtifactTypeDefinition,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


class ModelArtifactPayload(AIArtifactPayload):
    """Identify a model source without copying its live content or permissions."""

    model_label: str = Field(
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$"
    )


def authorize_model(payload: ModelArtifactPayload, request: HttpRequest) -> None:
    """Recheck model visibility when signing, sending or reading artifact context."""
    app_label, model_name = payload.model_label.split(".", 1)
    content_type = (
        UserPolicyManager(request.user)
        .get_accessible_content_types(BloomerpPermission.VIEW)
        .filter(app_label=app_label, model=model_name.lower())
        .first()
    )
    if content_type is None or content_type.model_class() is None:
        raise PermissionDenied("Model unavailable")


def search_models(
    request: HttpRequest, search: AIArtifactSearchRequest
) -> AIArtifactSearchPage[ModelArtifactPayload]:
    """Search accessible model labels and display names with stable label pagination."""
    query = search.query.casefold()
    labels: list[str] = []
    content_types = UserPolicyManager(request.user).get_accessible_content_types(
        BloomerpPermission.VIEW
    )
    for content_type in content_types:
        model = content_type.model_class()
        if model is None:
            continue
        label = model._meta.label
        if search.cursor and label <= search.cursor:
            continue
        searchable = (
            f"{label} {model._meta.verbose_name} {model._meta.verbose_name_plural}"
        )
        if query in searchable.casefold():
            labels.append(label)
    selected = sorted(labels)[: search.limit + 1]
    items = [
        ModelArtifactPayload(model_label=label) for label in selected[: search.limit]
    ]
    return AIArtifactSearchPage(
        items=items,
        cursor=items[-1].model_label if len(selected) > search.limit else None,
    )


def describe_model(payload: ModelArtifactPayload) -> AIArtifactDescription:
    """Describe the reference without fetching content or asserting target access."""
    return AIArtifactDescription(
        title=payload.model_label,
        summary=f"Reference to the {payload.model_label} model; schema and operations require authorized inspection.",
    )


MODEL_ARTIFACT = AIArtifactTypeDefinition[ModelArtifactPayload](
    key="model",
    label="Model",
    model=ModelArtifactPayload,
    describe=describe_model,
    authorize=authorize_model,
    search=search_models,
    icon="fa-table",
)
