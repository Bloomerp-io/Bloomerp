"""Render registered chat artifacts without exposing controller or tool internals."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.html import format_html
from django.views.decorators.http import require_GET

from bloomerp.agents.artifacts.registry import AI_ARTIFACT_REGISTRY
from bloomerp.models.agents import AIArtifact
from bloomerp.router import router


@router.register(
    path="components/agents/artifacts/<uuid:artifact_id>/",
    url_name="components_render_agent_artifact",
)
@login_required
@require_GET
def render_artifact(request: HttpRequest, artifact_id: UUID) -> HttpResponse:
    """Authorize conversation ownership and delegate presentation to the registered type."""
    artifact = get_object_or_404(
        AIArtifact, pk=artifact_id, conversation__owner=request.user
    )
    try:
        definition = AI_ARTIFACT_REGISTRY.get_type(
            artifact.kind, artifact.schema_version
        )
        payload = definition.model.model_validate(artifact.payload)
        if definition.authorize is not None:
            definition.authorize(payload, request)
        if definition.render_cls is not None:
            html = definition.render_cls.render(artifact.pk, payload, request)
        else:
            html = format_html(
                '<div class="rounded-lg border p-3 text-sm">{}</div>',
                definition.describe(payload).title,
            )
    except (PermissionDenied, LookupError, ValueError):
        html = format_html(
            '<div class="rounded-lg border p-3 text-sm">{}</div>',
            "Artifact unavailable",
        )
    response = HttpResponse(html)
    response["Cache-Control"] = "no-store"
    return response
