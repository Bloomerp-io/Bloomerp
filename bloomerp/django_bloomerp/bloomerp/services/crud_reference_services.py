"""Validate explicit reference payloads submitted by CRUD containers."""

import json
from dataclasses import dataclass
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest

from bloomerp.models import ApplicationField
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.object_reference_services import (
    Reference,
    parse_manual_references,
    validate_reference,
)


@dataclass(frozen=True)
class ReferenceSubmission:
    """Hold validated manual attachments and explicitly submitted field scopes."""

    fields: dict[int, list[Reference]]
    manual: list[Reference] | None


def prepare_reference_submission(
    request: HttpRequest, parent: models.Model, editable_fields: set[str]
) -> ReferenceSubmission | None:
    """Validate target identities and source permissions without parsing editor content."""
    if "object_references" not in request.POST:
        return None
    try:
        payload = json.loads(request.POST["object_references"])
        if not isinstance(payload, dict):
            raise ValueError("Expected reference payload")
        scopes = payload.get("fields", {})
        if not isinstance(scopes, dict) or len(scopes) > 200:
            raise ValueError("Invalid field scopes")
        manager = UserPolicyManager(request.user)
        permission = (
            BloomerpPermission.ADD
            if parent._state.adding
            else BloomerpPermission.CHANGE
        )
        allowed = (
            manager.has_global_permission(type(parent), permission)
            if parent._state.adding
            else manager.has_access_to_object(parent, permission)
        )
        if not request.user.is_authenticated or not allowed:
            raise ValidationError("Attachment permission denied.")
        accessible = (
            manager.get_accessible_fields(type(parent), permission)
            if parent._state.adding
            else manager.get_accessible_fields_for_object(parent, permission)
        )
        accessible_ids = set(accessible.values_list("pk", flat=True))
        content_type = ContentType.objects.get_for_model(parent)
        fields: dict[int, list[Reference]] = {}
        occurrences: set[UUID] = set()
        for field_key, entries in scopes.items():
            field_id = int(field_key)
            application_field = ApplicationField.objects.filter(
                pk=field_id, content_type=content_type
            ).first()
            if (
                application_field is None
                or field_id not in accessible_ids
                or application_field.field not in editable_fields
                or application_field.field not in request.POST
                or field_id in fields
            ):
                raise ValidationError("Reference field permission denied.")
            if not isinstance(entries, list) or len(entries) > 200:
                raise ValueError("Invalid occurrence list")
            references: list[Reference] = []
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("kind") not in {
                    "user",
                    "object",
                    "file",
                }:
                    raise ValueError("Invalid occurrence")
                occurrence = UUID(entry["occurrence_id"])
                if occurrence in occurrences or int(entry["field_id"]) != field_id:
                    raise ValueError("Invalid occurrence identity")
                occurrences.add(occurrence)
                target = str(entry["target_id"])
                if not target or len(target) > 255:
                    raise ValueError("Invalid target")
                reference = Reference(
                    entry["kind"],
                    target,
                    int(entry["content_type_id"])
                    if entry["kind"] == "object"
                    else None,
                    occurrence,
                    field_id,
                )
                validate_reference(request, reference, parent)
                references.append(reference)
            fields[field_id] = references
        manual = (
            parse_manual_references(json.dumps(payload["manual"]))
            if "manual" in payload
            else None
        )
        for reference in manual or []:
            validate_reference(request, reference, parent)
        return ReferenceSubmission(fields, manual)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValidationError("Malformed reference payload.") from error
