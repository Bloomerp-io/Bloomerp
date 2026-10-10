"""Validate and reconcile form-local manual attachments and editor occurrences."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from bloomerp.files.access import FileAccessManager, can_read_object_field
from bloomerp.models import (
    ApplicationField,
    BloomerpModel,
    FileNode,
    FileReference,
    Label,
    Mention,
    ObjectLabel,
    Tag,
)
from bloomerp.models.definition import get_model_config
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.utils.models import get_detail_view_url


@dataclass(frozen=True)
class Reference:
    """Identify a selected target and optionally one serialized editor occurrence."""

    kind: str
    target_id: str
    content_type_id: int | None = None
    occurrence_id: UUID | None = None
    field_id: int | None = None


def supports_object_references(model: type[models.Model]) -> bool:
    """Limit target discovery to configured application models rather than framework tables."""
    config = getattr(model, "bloomerp_config", None)
    return not getattr(config, "is_internal", False) and (
        issubclass(model, BloomerpModel) or config is not None
    )


def can_change_label(user: Any, label: Label) -> bool:
    """Allow administrators and the creator to edit a shared label."""
    return user.is_authenticated and (
        user.is_superuser or label.created_by_id == user.pk
    )


def reference_display(request: HttpRequest, obj: models.Model) -> str | None:
    """Return the readable object's representation or a user's full display name."""
    model = type(obj)
    if not UserPolicyManager(request.user).has_access_to_object(
        obj, BloomerpPermission.VIEW
    ):
        return None
    if model is get_user_model():
        return (obj.get_full_name().strip() or obj.username)[:160]
    return str(obj)[:160] or None


def object_reference_metadata(obj: models.Model) -> dict[str, str]:
    """Describe a readable object tag using its configured icon and detail route."""
    config = get_model_config(type(obj))
    metadata = {"icon": config.icon if config and config.icon else "fa-solid fa-cube"}
    try:
        metadata["url"] = reverse(get_detail_view_url(type(obj)), kwargs={"pk": obj.pk})
    except NoReverseMatch:
        pass
    return metadata


def parse_editor_references(
    content: str, application_field: ApplicationField
) -> tuple[str, list[Reference]]:
    """Extract stable target identities and canonicalize referenced image serving URLs."""
    soup = BeautifulSoup(content or "", "html.parser")
    references: list[Reference] = []
    seen: set[UUID] = set()
    for node in soup.select("[data-reference-kind]"):
        try:
            kind = node["data-reference-kind"]
            if kind not in {"user", "object", "file"}:
                raise ValueError("Unknown reference kind")
            occurrence = UUID(node["data-occurrence-id"])
            if occurrence in seen:
                raise ValueError("Duplicate occurrence identity")
            seen.add(occurrence)
            target_id = str(node["data-target-id"])
            if not target_id or len(target_id) > 255:
                raise ValueError("Invalid target")
            content_type_id = (
                int(node["data-target-content-type-id"]) if kind == "object" else None
            )
            references.append(
                Reference(
                    kind, target_id, content_type_id, occurrence, application_field.pk
                )
            )
            if kind == "file":
                UUID(target_id)
                if node.name != "img":
                    raise ValueError("Only image references are supported")
                node["src"] = reverse("api_files_serve") + "?file_id=" + target_id
        except (ValueError, TypeError, KeyError) as error:
            raise ValidationError("Malformed editor reference.") from error
    return (str(soup) if references else content), references


def parse_manual_references(value: str) -> list[Reference]:
    """Validate the bounded manual attachment payload independently of its display labels."""
    try:
        entries = json.loads(value)
        if not isinstance(entries, list) or len(entries) > 200:
            raise ValueError("Invalid attachment list")
        result: list[Reference] = []
        for entry in entries:
            kind = entry["kind"]
            if kind not in {"user", "object", "file", "label"}:
                raise ValueError("Unknown attachment type")
            target = str(entry["target_id"])
            if not target or len(target) > 255:
                raise ValueError("Invalid target")
            result.append(
                Reference(
                    kind,
                    target,
                    int(entry["content_type_id"]) if kind == "object" else None,
                )
            )
        return list(dict.fromkeys(result))
    except (ValueError, TypeError, KeyError) as error:
        raise ValidationError("Malformed attachments.") from error


def validate_reference(
    request: HttpRequest | None, reference: Reference, parent: models.Model
) -> None:
    """Reject forged, inaccessible, or incompatible attachment targets before saving."""
    if request is None or not request.user.is_authenticated:
        raise ValidationError("An authenticated request is required for references.")
    try:
        if reference.kind == "user":
            target = get_user_model().objects.get(
                pk=reference.target_id, is_active=True, is_staff=True
            )
            if reference_display(request, target) is None:
                raise ValidationError("User unavailable.")
        elif reference.kind == "object":
            content_type = ContentType.objects.get(pk=reference.content_type_id)
            model = content_type.model_class()
            if model is None or not supports_object_references(model):
                raise ValidationError("Object unavailable.")
            target = model._base_manager.get(pk=reference.target_id)
            if reference_display(request, target) is None:
                raise ValidationError("Object unavailable.")
        elif reference.kind == "file":
            target = FileNode.objects.get(pk=reference.target_id)
            if not FileAccessManager(request.user).can_read_file_node(target):
                raise ValidationError("File unavailable.")

        else:
            Label.objects.get(pk=reference.target_id)
    except (ObjectDoesNotExist, ValueError, TypeError) as error:
        raise ValidationError("Reference target unavailable.") from error


@transaction.atomic
def reconcile_references(
    parent: models.Model,
    fields: dict[int, list[Reference]],
    manual: list[Reference] | None,
    request: HttpRequest | None,
    *,
    source_operation: str = "change",
) -> None:
    """Replace submitted scopes atomically while preserving omitted fields and comments."""
    content_type = ContentType.objects.get_for_model(parent)
    file_ids = {
        reference.target_id
        for entries in [*fields.values(), manual or []]
        for reference in entries
        if reference.kind == "file"
    }
    # Lock shared nodes and revalidate readability before changing their usages.
    list(FileNode.objects.select_for_update().filter(pk__in=file_ids).order_by("pk"))
    for entries in [*fields.values(), manual or []]:
        for reference in entries:
            validate_reference(request, reference, parent)
    current_files = {
        str(pk)
        for pk in FileReference.objects.filter(
            content_type=content_type,
            object_id=str(parent.pk),
            application_field__isnull=True,
            occurrence_id__isnull=True,
        ).values_list("file_id", flat=True)
    }
    can_change_files = request is not None and UserPolicyManager(
        request.user
    ).has_access_to_object(parent, source_operation, fields=["files"])
    submitted_files = {
        reference.target_id for reference in manual or [] if reference.kind == "file"
    }
    if manual is not None and submitted_files - current_files and not can_change_files:
        raise ValidationError("File attachment permission denied.")
    with transaction.atomic():
        type(parent)._base_manager.select_for_update().get(pk=parent.pk)
        for field_id, references in fields.items():
            Mention.objects.filter(
                content_type=content_type,
                object_id=str(parent.pk),
                application_field_id=field_id,
            ).delete()
            Tag.objects.filter(
                source_content_type=content_type,
                source_object_id=str(parent.pk),
                application_field_id=field_id,
            ).delete()
            FileReference.objects.filter(
                content_type=content_type,
                application_field_id=field_id,
                object_id=str(parent.pk),
                occurrence_id__isnull=False,
            ).delete()
            for reference in references:
                if reference.kind == "user":
                    Mention.objects.create(
                        content_type=content_type,
                        object_id=str(parent.pk),
                        application_field_id=field_id,
                        occurrence_id=reference.occurrence_id,
                        user_id=reference.target_id,
                    )
                elif reference.kind == "object":
                    Tag.objects.create(
                        source_content_type=content_type,
                        source_object_id=str(parent.pk),
                        application_field_id=field_id,
                        occurrence_id=reference.occurrence_id,
                        target_content_type_id=reference.content_type_id,
                        target_object_id=reference.target_id,
                    )
                else:
                    FileReference.objects.create(
                        content_type=content_type,
                        file_id=reference.target_id,
                        application_field_id=field_id,
                        object_id=str(parent.pk),
                        occurrence_id=reference.occurrence_id,
                    )
        if manual is None:
            return
        # Retain inaccessible existing entries: this form cannot knowingly remove them.
        for record in Mention.objects.filter(
            content_type=content_type,
            object_id=str(parent.pk),
            application_field__isnull=True,
        ).select_related("user"):
            if reference_display(request, record.user) is not None:
                record.delete()
        for record in Tag.objects.filter(
            source_content_type=content_type,
            source_object_id=str(parent.pk),
            application_field__isnull=True,
        ):
            model = record.target_content_type.model_class()
            target = (
                model._base_manager.filter(pk=record.target_object_id).first()
                if model
                else None
            )
            if target is None or reference_display(request, target) is not None:
                record.delete()
        ObjectLabel.objects.filter(
            content_type=content_type, object_id=str(parent.pk)
        ).delete()
        retained_files = [entry.target_id for entry in manual if entry.kind == "file"]
        if can_change_files and can_read_object_field(request, parent, "files"):
            FileReference.objects.filter(
                content_type=content_type,
                object_id=str(parent.pk),
                application_field__isnull=True,
                occurrence_id__isnull=True,
            ).exclude(file_id__in=retained_files).delete()
        for reference in manual:
            if reference.kind == "user":
                Mention.objects.get_or_create(
                    content_type=content_type,
                    object_id=str(parent.pk),
                    user_id=reference.target_id,
                    application_field=None,
                )
            elif reference.kind == "object":
                Tag.objects.get_or_create(
                    source_content_type=content_type,
                    source_object_id=str(parent.pk),
                    target_content_type_id=reference.content_type_id,
                    target_object_id=reference.target_id,
                    application_field=None,
                )
            elif reference.kind == "label":
                ObjectLabel.objects.get_or_create(
                    content_type=content_type,
                    object_id=str(parent.pk),
                    label_id=reference.target_id,
                )
            else:
                FileReference.objects.get_or_create(
                    file_id=reference.target_id,
                    content_type=content_type,
                    object_id=str(parent.pk),
                    application_field=None,
                    occurrence_id=None,
                )
        parent.__dict__.pop("_prefetched_objects_cache", None)


def object_reference_state(
    request: HttpRequest, parent: models.Model
) -> list[dict[str, Any]]:
    """Return visible manual and field references without including nested comments."""
    if parent._state.adding:
        return []
    content_type = ContentType.objects.get_for_model(parent)
    result: list[dict[str, Any]] = []

    def append(
        reference: Reference, label: str, target: models.Model | None = None
    ) -> None:
        """Expose one chip identity without conflating repeated occurrences."""
        result.append(
            {
                "kind": reference.kind,
                "target_id": reference.target_id,
                "content_type_id": reference.content_type_id,
                "field_id": reference.field_id,
                "occurrence_id": str(reference.occurrence_id)
                if reference.occurrence_id
                else None,
                "label": label,
                **(object_reference_metadata(target) if target is not None else {}),
            }
        )

    for record in Mention.objects.filter(
        content_type=content_type, object_id=str(parent.pk)
    ).select_related("user", "application_field"):
        if record.application_field_id and not can_read_object_field(
            request, parent, record.application_field.field
        ):
            continue
        label = reference_display(request, record.user)
        if label:
            append(
                Reference(
                    "user",
                    str(record.user_id),
                    occurrence_id=record.occurrence_id,
                    field_id=record.application_field_id,
                ),
                label,
            )
    for record in Tag.objects.filter(
        source_content_type=content_type, source_object_id=str(parent.pk)
    ).select_related("target_content_type", "application_field"):
        if record.application_field_id and not can_read_object_field(
            request, parent, record.application_field.field
        ):
            continue
        model = record.target_content_type.model_class()
        target = (
            model._base_manager.filter(pk=record.target_object_id).first()
            if model
            else None
        )
        label = reference_display(request, target) if target else None
        if label:
            append(
                Reference(
                    "object",
                    record.target_object_id,
                    record.target_content_type_id,
                    record.occurrence_id,
                    record.application_field_id,
                ),
                label,
                target,
            )
    for record in ObjectLabel.objects.filter(
        content_type=content_type, object_id=str(parent.pk)
    ).select_related("label"):
        append(Reference("label", str(record.label_id)), record.label.name)
    for record in FileReference.objects.filter(
        content_type=content_type,
        object_id=str(parent.pk),
        occurrence_id__isnull=False,
    ).select_related("file", "application_field"):
        if can_read_object_field(request, parent, record.application_field.field):
            append(
                Reference(
                    "file",
                    str(record.file_id),
                    occurrence_id=record.occurrence_id,
                    field_id=record.application_field_id,
                ),
                record.file.name or "Image",
            )
    if can_read_object_field(request, parent, "files"):
        for record in FileReference.objects.filter(
            content_type=content_type,
            object_id=str(parent.pk),
            application_field__isnull=True,
            occurrence_id__isnull=True,
        ).select_related("file"):
            append(Reference("file", str(record.file_id)), record.file.name or "File")
    return result


def manual_reference_state(
    request: HttpRequest, parent: models.Model, references: list[Reference]
) -> list[dict[str, Any]]:
    """Restore valid submitted attachment chips when another field fails validation."""
    result: list[dict[str, Any]] = []
    for reference in references:
        try:
            validate_reference(request, reference, parent)
            if reference.kind == "user":
                label = reference_display(
                    request, get_user_model().objects.get(pk=reference.target_id)
                )
            elif reference.kind == "object":
                model = ContentType.objects.get(
                    pk=reference.content_type_id
                ).model_class()
                target = model._base_manager.get(pk=reference.target_id)
                label = reference_display(request, target)
            elif reference.kind == "file":
                label = FileNode.objects.get(pk=reference.target_id).name
            else:
                label = Label.objects.get(pk=reference.target_id).name
            result.append(
                {
                    "kind": reference.kind,
                    "target_id": reference.target_id,
                    "content_type_id": reference.content_type_id,
                    "label": label or "Reference",
                    **(
                        object_reference_metadata(target)
                        if reference.kind == "object"
                        else {}
                    ),
                }
            )
        except (ValidationError, ObjectDoesNotExist):
            continue
    return result
