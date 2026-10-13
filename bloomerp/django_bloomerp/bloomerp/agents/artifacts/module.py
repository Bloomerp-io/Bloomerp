"""Searchable module context using the same visibility rules as module home pages."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.utils.html import format_html
from pydantic import Field

from bloomerp.agents.definition import (
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactRenderer,
    AIArtifactSearchPage,
    AIArtifactSearchRequest,
    AIArtifactTypeDefinition,
)

if TYPE_CHECKING:
    from bloomerp.modules.definition import ModuleConfig
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


class ModuleArtifactPayload(AIArtifactPayload):
    """Identify a module and retain the selected human-readable context."""

    module_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)


def authorize_module(payload: ModuleArtifactPayload, request: HttpRequest) -> None:
    """Recheck module access when sending, rendering or building runtime context."""
    if not any(
        (module.full_id or module.id) == payload.module_id
        for module in UserPolicyManager(request.user).get_accessible_modules(
            BloomerpPermission.VIEW
        )
    ):
        raise PermissionDenied("Module unavailable")


def search_modules(
    request: HttpRequest, search: AIArtifactSearchRequest
) -> AIArtifactSearchPage[ModuleArtifactPayload]:
    """Search authorized module names and descriptions with stable key pagination."""
    modules = sorted(
        UserPolicyManager(request.user).get_accessible_modules(BloomerpPermission.VIEW),
        key=module_identity,
    )
    selected = [
        module
        for module in modules
        if (not search.cursor or module_identity(module) > search.cursor)
        and search.query.casefold()
        in f"{module.localized_name} {module.localized_description}".casefold()
    ][: search.limit + 1]
    items = [
        ModuleArtifactPayload(
            module_id=module_identity(module),
            name=module.localized_name,
            description=module.localized_description,
        )
        for module in selected[: search.limit]
    ]
    return AIArtifactSearchPage(
        items=items,
        cursor=items[-1].module_id if len(selected) > search.limit else None,
    )


def module_identity(module: ModuleConfig) -> str:
    """Return the stable qualified module identifier for sorting and references."""
    return module.full_id or module.id


def describe_module(payload: ModuleArtifactPayload) -> AIArtifactDescription:
    """Provide module context without loading any business records."""
    return AIArtifactDescription(
        title=payload.name, summary=f"Module {payload.module_id}: {payload.description}"
    )


class ModuleArtifactRenderer(AIArtifactRenderer[ModuleArtifactPayload]):
    """Render an escaped module context card after rechecking access."""

    @classmethod
    def render(
        cls, artifact_id: UUID, payload: ModuleArtifactPayload, request: HttpRequest
    ) -> str:
        """Show the selected module without implying access to all its records."""
        authorize_module(payload, request)
        return format_html(
            '<div class="rounded-xl border p-3 text-sm"><strong>{}</strong><p class="text-xs text-gray-500">{}</p></div>',
            payload.name,
            payload.description,
        )


MODULE_ARTIFACT = AIArtifactTypeDefinition[ModuleArtifactPayload](
    key="module",
    label="Modules",
    model=ModuleArtifactPayload,
    describe=describe_module,
    authorize=authorize_module,
    search=search_modules,
    render_cls=ModuleArtifactRenderer,
    icon="fa-layer-group",
)
