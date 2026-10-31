"""Read and save reusable layouts and document-specific signing preparations."""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import PermissionDenied, ValidationError

from bloomerp.models.document_signing import (
    SignatureLayout,
    SignatureLayoutField,
    SignatureLayoutRole,
    SignaturePreparation,
    SignaturePreparationField,
    SignaturePreparationRole,
)
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

from .access import (
    LAYOUT_FIELDS,
    LAYOUT_PLACEMENT_FIELDS,
    LAYOUT_ROLE_FIELDS,
    PREPARATION_FIELDS,
    PREPARATION_PLACEMENT_FIELDS,
    PREPARATION_ROLE_FIELDS,
    can_save_preparation,
    can_save_signing_default,
    can_use_layout,
    get_signing_layout_revisions,
    require_signing_access,
)


def signing_default_payload(
    template: DocumentTemplate,
    manager: UserPolicyManager,
    layout_id: UUID | None = None,
) -> dict[str, Any]:
    """Expose readable revision choices and the selected template-owned layout snapshot."""
    layouts = get_signing_layout_revisions(template, manager)
    selected_id = layout_id or template.default_signature_layout_id
    layout = next((item for item in layouts if item.pk == selected_id), None)
    if selected_id is not None and layout is None:
        raise PermissionDenied(
            "This layout revision is not available for this document template."
        )
    payload: dict[str, Any] = {
        "document_template_id": str(template.pk),
        "default_layout_id": str(template.default_signature_layout_id)
        if template.default_signature_layout_id
        else None,
        "revisions": [
            {
                "id": str(item.pk),
                "revision": item.revision,
                "is_default": item.pk == template.default_signature_layout_id,
            }
            for item in layouts
        ],
        "can_save": can_save_signing_default(template, manager),
        "layout": None,
    }
    if layout is None:
        return payload
    require_signing_access(layout, manager, BloomerpPermission.VIEW, LAYOUT_FIELDS)
    roles = list(layout.roles.all())
    fields = list(layout.fields.select_related("role"))
    for role in roles:
        require_signing_access(
            role, manager, BloomerpPermission.VIEW, LAYOUT_ROLE_FIELDS
        )
    for field in fields:
        require_signing_access(
            field, manager, BloomerpPermission.VIEW, LAYOUT_PLACEMENT_FIELDS
        )
    payload["layout"] = {
        "id": str(layout.pk),
        "name": layout.name,
        "revision": layout.revision,
        "roles": [
            {
                "key": role.key,
                "label": role.label,
                "default_signing_order": role.default_signing_order,
            }
            for role in roles
        ],
        "fields": [
            {
                "role_key": field.role.key,
                **{
                    name: getattr(field, name)
                    for name in LAYOUT_PLACEMENT_FIELDS
                    if name not in {"layout", "role"}
                },
            }
            for field in fields
        ],
    }
    return payload


def save_signing_default(
    file: FileNode,
    template: DocumentTemplate,
    manager: UserPolicyManager,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Atomically create a fresh revision and replace only this template's default link."""
    with transaction.atomic():
        template = DocumentTemplate.objects.select_for_update().get(pk=template.pk)
        if (
            not file.get_references(models=[DocumentTemplate])
            .select_for_update()
            .filter(
                object_id=str(template.pk),
                application_field__isnull=True,
                occurrence_id__isnull=True,
            )
            .exists()
        ):
            raise PermissionDenied(
                "This PDF no longer references the document template."
            )
        if not can_save_signing_default(template, manager):
            raise PermissionDenied(
                "You cannot save this document template's signing layout."
            )
        expected = data["expected_layout_id"]
        current = template.default_signature_layout
        if (str(current.pk) if current else None) != (
            str(expected) if expected else None
        ):
            raise ValidationError(
                "The default signing layout changed. Load the latest layout before saving again."
            )
        if current:
            require_signing_access(
                current, manager, BloomerpPermission.VIEW, LAYOUT_FIELDS
            )
        latest_revision = (
            SignatureLayout.objects.filter(document_template=template).aggregate(
                latest=Max("revision")
            )["latest"]
            or 0
        )
        layout = SignatureLayout(
            document_template=template,
            name=template.name,
            revision=max(latest_revision, current.revision if current else 0) + 1,
            preview_file=file,
        )
        layout.save()
        require_signing_access(layout, manager, BloomerpPermission.ADD, LAYOUT_FIELDS)
        roles = {}
        for values in data["roles"]:
            role = SignatureLayoutRole(
                layout=layout,
                **values,
            )
            role.save()
            require_signing_access(
                role, manager, BloomerpPermission.ADD, LAYOUT_ROLE_FIELDS
            )
            roles[role.key] = role
        for values in data["fields"]:
            placement = dict(values)
            role = roles[placement.pop("role_key")]
            field = SignatureLayoutField(
                layout=layout,
                role=role,
                **placement,
            )
            field.save()
            require_signing_access(
                field, manager, BloomerpPermission.ADD, LAYOUT_PLACEMENT_FIELDS
            )
        template.default_signature_layout = layout
        template.save(
            update_fields=["default_signature_layout", "updated_by", "datetime_updated"]
        )
        return signing_default_payload(template, manager)


def preparation_payload(
    preparation: SignaturePreparation, manager: UserPolicyManager
) -> dict[str, Any]:
    """Return a complete editable preparation after checking every role and placement."""
    require_signing_access(
        preparation, manager, BloomerpPermission.VIEW, PREPARATION_FIELDS
    )
    roles = list(preparation.roles.all())
    fields = list(preparation.fields.select_related("role"))
    for role in roles:
        require_signing_access(
            role, manager, BloomerpPermission.VIEW, PREPARATION_ROLE_FIELDS
        )
    for field in fields:
        require_signing_access(
            field, manager, BloomerpPermission.VIEW, PREPARATION_PLACEMENT_FIELDS
        )
    return {
        "id": str(preparation.pk),
        "revision": preparation.revision,
        "title": preparation.title,
        "source_layout": str(preparation.source_layout_id)
        if preparation.source_layout_id
        else None,
        "roles": [
            {
                "key": role.key,
                "label": role.label,
                "default_signing_order": role.signing_order,
            }
            for role in roles
        ],
        "fields": [
            {
                "role_key": field.role.key,
                **{
                    name: getattr(field, name)
                    for name in PREPARATION_PLACEMENT_FIELDS
                    if name not in {"preparation", "role"}
                },
            }
            for field in fields
        ],
    }


def save_preparation(
    file: FileNode, manager: UserPolicyManager, data: dict[str, Any]
) -> dict[str, Any]:
    """Atomically save a role-based draft while retaining existing record identities."""
    with transaction.atomic():
        preparation = (
            SignaturePreparation.objects.select_for_update()
            .filter(pk=data["id"])
            .first()
        )
        creating = preparation is None
        permission = BloomerpPermission.ADD if creating else BloomerpPermission.CHANGE
        if not can_save_preparation(manager, permission):
            raise PermissionDenied("You cannot save signing preparations.")
        if creating:
            if data["revision"] != 0:
                raise ValidationError(
                    "This preparation no longer exists. Reload the document."
                )
            preparation = SignaturePreparation(id=data["id"], original_file=file)
        else:
            if preparation.requests.filter(status="draft").exists():
                raise ValidationError(
                    "This preparation belongs to a saved signing request. Start a new preparation to make changes."
                )
            if preparation.original_file_id != file.pk:
                raise PermissionDenied("This preparation belongs to another PDF.")
            require_signing_access(preparation, manager, permission, PREPARATION_FIELDS)
            if preparation.revision != data["revision"]:
                raise ValidationError(
                    "This preparation changed elsewhere. Reload before saving again."
                )
            preparation.revision += 1
        source = None
        if data["source_layout"]:
            source = SignatureLayout.objects.filter(pk=data["source_layout"]).first()
            if not can_use_layout(source, manager):
                raise PermissionDenied("You cannot use this signing layout.")
        preparation.title = data["title"]
        preparation.source_layout = source
        preparation.save()
        require_signing_access(preparation, manager, permission, PREPARATION_FIELDS)

        existing_roles = {role.key: role for role in preparation.roles.all()}
        existing_fields = {field.key: field for field in preparation.fields.all()}
        field_keys = {field["key"] for field in data["fields"]}
        role_keys = {role["key"] for role in data["roles"]}
        for key, field in existing_fields.items():
            if key not in field_keys:
                require_signing_access(
                    field,
                    manager,
                    BloomerpPermission.DELETE,
                    PREPARATION_PLACEMENT_FIELDS,
                )
                field.delete()
        roles = {}
        for values in data["roles"]:
            role = existing_roles.get(values["key"])
            role_permission = (
                BloomerpPermission.CHANGE if role else BloomerpPermission.ADD
            )
            if role:
                require_signing_access(
                    role, manager, role_permission, PREPARATION_ROLE_FIELDS
                )
            else:
                role = SignaturePreparationRole(
                    preparation=preparation, key=values["key"]
                )
            role.label = values["label"]
            role.signing_order = values["default_signing_order"]
            role.save()
            require_signing_access(
                role, manager, role_permission, PREPARATION_ROLE_FIELDS
            )
            roles[role.key] = role
        for values in data["fields"]:
            field = existing_fields.get(values["key"])
            field_permission = (
                BloomerpPermission.CHANGE if field else BloomerpPermission.ADD
            )
            if field:
                require_signing_access(
                    field, manager, field_permission, PREPARATION_PLACEMENT_FIELDS
                )
            else:
                field = SignaturePreparationField(
                    preparation=preparation, key=values["key"]
                )
            placement = dict(values)
            field.role = roles[placement.pop("role_key")]
            for name, value in placement.items():
                setattr(field, name, value)
            field.save()
            require_signing_access(
                field, manager, field_permission, PREPARATION_PLACEMENT_FIELDS
            )
        for key, role in existing_roles.items():
            if key not in role_keys:
                require_signing_access(
                    role, manager, BloomerpPermission.DELETE, PREPARATION_ROLE_FIELDS
                )
                role.delete()
        return preparation_payload(preparation, manager)
