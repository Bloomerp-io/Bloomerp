"""Resolve signed picker candidates and editor references for chat attachments."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from pydantic import Field

from bloomerp.agents.definition import (
    AgentPayload,
    AIArtifactPayload,
    AIArtifactTypeDefinition,
)

from .file import FILE_ARTIFACT, FileArtifactPayload
from .object import OBJECT_ARTIFACT, ObjectArtifactPayload
from .registry import AI_ARTIFACT_REGISTRY

SALT = "bloomerp.agent.attachment"


class EditorAttachment(AgentPayload):
    """Carry only the identity of an inline object or stored image."""

    kind: Literal["object", "file"]
    target_id: str = Field(min_length=1, max_length=255)
    content_type_id: int | None = Field(
        default=None, gt=0, le=2_147_483_647, strict=True
    )


def selection_item(
    definition: AIArtifactTypeDefinition,
    payload: AIArtifactPayload,
    request: HttpRequest,
) -> dict[str, Any]:
    """Sign server-produced metadata so draft clients cannot forge source descriptions."""
    validated = definition.model.model_validate(payload.model_dump(mode="json"))
    if definition.authorize:
        definition.authorize(validated, request)
    body = {
        "type": definition.key,
        "version": definition.schema_version,
        "payload": validated.model_dump(mode="json"),
    }
    description = definition.describe(validated)
    return {
        "token": signing.dumps(
            {**body, "user": str(request.user.pk)}, salt=SALT, compress=True
        ),
        "key": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
        "type": definition.key,
        "title": description.title,
        "summary": description.summary,
        "icon": definition.icon or "fa-paperclip",
    }


def _editor_payload(
    reference: EditorAttachment,
) -> tuple[AIArtifactTypeDefinition, AIArtifactPayload]:
    """Resolve an editor identity to registered attachment metadata for authorization."""
    from bloomerp.models import FileNode
    from bloomerp.services.object_reference_services import supports_object_references

    if reference.kind == "file":
        file = FileNode.objects.filter(
            pk=UUID(reference.target_id), kind="FILE"
        ).first()
        if file is None:
            raise PermissionDenied("Attachment unavailable")
        return FILE_ARTIFACT, FileArtifactPayload(
            file_id=file.pk,
            name=file.name or str(file.pk),
            media_type=file.meta.get("mime_type") or "application/octet-stream",
        )
    content_type = ContentType.objects.filter(pk=reference.content_type_id).first()
    model = content_type.model_class() if content_type else None
    if model is None or not supports_object_references(model):
        raise PermissionDenied("Attachment unavailable")
    return OBJECT_ARTIFACT, ObjectArtifactPayload(
        model_label=model._meta.label,
        object_id=reference.target_id,
    )


def _signed_payload(
    token: str, request: HttpRequest
) -> tuple[AIArtifactTypeDefinition, AIArtifactPayload]:
    """Read the metadata from a current picker token belonging to this user."""
    try:
        body = signing.loads(token, salt=SALT, max_age=86400)
    except signing.BadSignature as error:
        raise PermissionDenied(
            "Attachment expired or invalid; please select it again"
        ) from error
    if body.get("user") != str(request.user.pk):
        raise PermissionDenied("Attachment belongs to another user")
    definition = AI_ARTIFACT_REGISTRY.get_type(body["type"], body["version"])
    if definition.search is None and definition.upload is None:
        raise PermissionDenied("This artifact cannot be manually attached")
    return definition, definition.model.model_validate(body["payload"])


def resolve_selection(
    selection: str | EditorAttachment, request: HttpRequest
) -> dict[str, Any]:
    """Reauthorize picker selections and editor references through the same artifact rules."""
    definition, payload = (
        _editor_payload(selection)
        if isinstance(selection, EditorAttachment)
        else _signed_payload(selection, request)
    )
    if definition.authorize:
        definition.authorize(payload, request)
    return {
        "kind": definition.key,
        "schema_version": definition.schema_version,
        "payload": payload.model_dump(mode="json"),
        "file_id": definition.selection_file_id(payload)
        if definition.selection_file_id
        else None,
    }
