from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models

from bloomerp.models import ApplicationField, UserCreateViewPreference
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import create_default_layout


AUTO_MANAGED_FIELD_NAMES = {
    "id",
    "pk",
    "datetime_created",
    "datetime_updated",
    "created_by",
    "updated_by",
}


@dataclass
class CreateAccessState:
    """Aggregate the permissions-derived state required to render or block a create view."""
    addable_fields: models.QuerySet[ApplicationField]
    required_fields: list[ApplicationField]
    missing_required_fields: list[ApplicationField]
    has_add_row_rules: bool

    @property
    def is_blocked(self) -> bool:
        """Return whether create access must be blocked before submission."""
        return bool(self.missing_required_fields) or not self.has_add_row_rules

    @property
    def blocked_message(self) -> str | None:
        """Return the user-facing reason why the create view is blocked, if any."""
        if self.missing_required_fields:
            field_titles = ", ".join(sorted(field.title for field in self.missing_required_fields))
            return (
                "You do not have permission to create this object because you do not have access "
                f"to the required fields: {field_titles}."
            )
        if not self.has_add_row_rules:
            return "You do not have permission to create this object because no create row policy applies to you."
        return None


def get_default_layout(content_type: ContentType, user) -> FieldLayout:
    """Build the default create-view layout restricted to fields the user may add."""
    model = content_type.model_class()
    if model is None:
        return FieldLayout(rows=[])

    addable_fields = list(get_addable_fields(content_type=content_type, user=user))
    return create_default_layout(model, application_fields=addable_fields)


def create_default_create_view_preference(content_type: ContentType, user) -> UserCreateViewPreference:
    """Create and persist the initial per-user create-view layout preference."""
    default_layout = get_default_layout(content_type=content_type, user=user)
    return UserCreateViewPreference.objects.create(
        user=user,
        content_type=content_type,
        field_layout=default_layout.model_dump(),
    )


def get_addable_fields(*, content_type: ContentType, user) -> models.QuerySet[ApplicationField]:
    """Return application fields the user may add on the create view for a content type."""
    model = content_type.model_class()
    if model is None:
        return ApplicationField.objects.none()

    permission_manager = UserPermissionManager(user)
    permission_str = create_permission_str(model, "add")
    accessible_fields = permission_manager.get_accessible_fields(content_type, permission_str).order_by("field")
    allowed_ids: list[int] = []
    for application_field in accessible_fields:
        if application_field.field in AUTO_MANAGED_FIELD_NAMES:
            continue
        try:
            model_field = application_field._get_model_field()
        except Exception:
            continue
        if not getattr(model_field, "editable", True):
            continue
        if not getattr(model_field, "concrete", True):
            continue
        try:
            form_field = application_field.get_form_field()
        except Exception:
            continue
        if form_field is None:
            continue
        allowed_ids.append(application_field.pk)

    return ApplicationField.objects.filter(id__in=allowed_ids).order_by("field")


def get_required_create_fields(*, content_type: ContentType) -> list[ApplicationField]:
    """Return required model-backed application fields that must be creatable by the user."""
    model = content_type.model_class()
    if model is None:
        return []

    required_fields: list[ApplicationField] = []
    for model_field in model._meta.concrete_fields:
        if model_field.name in AUTO_MANAGED_FIELD_NAMES:
            continue
        if getattr(model_field, "auto_created", False):
            continue
        if not getattr(model_field, "editable", True):
            continue
        if getattr(model_field, "null", False) or getattr(model_field, "blank", False):
            continue
        if getattr(model_field, "has_default", lambda: False)():
            continue
        if getattr(model_field, "auto_now", False) or getattr(model_field, "auto_now_add", False):
            continue

        application_field = ApplicationField.get_by_field(model, model_field.name)
        if application_field is not None:
            required_fields.append(application_field)

    return required_fields


def get_create_access_state(*, content_type: ContentType, user) -> CreateAccessState:
    """Compute the field and row-policy state used to allow or block create access."""
    addable_fields = get_addable_fields(content_type=content_type, user=user)
    addable_field_names = set(addable_fields.values_list("field", flat=True))
    required_fields = get_required_create_fields(content_type=content_type)
    missing_required_fields = [field for field in required_fields if field.field not in addable_field_names]

    model = content_type.model_class()
    permission_manager = UserPermissionManager(user)
    add_permission_str = create_permission_str(model, "add") if model else ""

    return CreateAccessState(
        addable_fields=addable_fields,
        required_fields=required_fields,
        missing_required_fields=missing_required_fields,
        has_add_row_rules=bool(model and permission_manager.has_row_level_access(model, add_permission_str)),
    )


def get_disallowed_submitted_fields(*, model, submitted_data: dict[str, Any], allowed_field_names: set[str]) -> list[str]:
    """Return submitted model field names that were posted without create permission."""
    denied_fields: list[str] = []
    for field_name in submitted_data.keys():
        if field_name in {"csrfmiddlewaretoken"}:
            continue
        if field_name not in allowed_field_names and ApplicationField.get_by_field(model, field_name):
            denied_fields.append(field_name)
    return sorted(set(denied_fields))
