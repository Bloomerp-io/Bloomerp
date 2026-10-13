"""Signed, owner-bound attachment candidates shared by discovery and message ingestion."""

import hashlib
import json
from typing import Any

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from bloomerp.agents.definition import AIArtifactPayload, AIArtifactTypeDefinition

from .registry import AI_ARTIFACT_REGISTRY

SALT = "bloomerp.agent.attachment"


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


def resolve_selection(token: str, request: HttpRequest) -> dict[str, Any]:
    """Reauthorize a signed candidate at send time, independent of UI visibility."""
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
    payload = definition.model.model_validate(body["payload"])
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
