from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import FieldLayout
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str


ROW_KEY_SEPARATOR = "__"
ROW_ID_KEY = "id"
ROW_DELETE_KEY = "DELETE"


@dataclass(frozen=True)
class OneToManySaveConfig:
    """The resolved save contract for one inline one-to-many field."""

    application_field: ApplicationField
    related_model: type[models.Model]
    parent_fk_name: str
    editable_fields: list[ApplicationField]

    @property
    def prefix(self) -> str:
        return self.application_field.field


def save_submitted_one_to_many_fields(
    *,
    parent_object: models.Model,
    layout: FieldLayout,
    submitted_data: Mapping[str, Any],
    user,
) -> None:
    """Persist one-to-many inline table rows posted with a CRUD layout form.

    The widget owns only the input naming contract:
    ``<reverse-field-name>__<row-index>__<field-name>``.
    This service owns the persistence rules because it has access to the saved
    parent object, permissions, and the layout configuration that decides which
    related fields are editable inline.
    """
    permission_manager = UserPermissionManager(user)
    errors: list[str] = []

    for config in iter_one_to_many_save_configs(
        parent_model=type(parent_object),
        layout=layout,
        permission_manager=permission_manager,
    ):
        try:
            _save_one_to_many_field(
                parent_object=parent_object,
                config=config,
                submitted_data=submitted_data,
                permission_manager=permission_manager,
            )
        except ValidationError as exc:
            errors.extend(_flatten_validation_error(exc))

    if errors:
        raise ValidationError(errors)


def iter_one_to_many_save_configs(
    *,
    parent_model: type[models.Model],
    layout: FieldLayout,
    permission_manager: UserPermissionManager,
) -> list[OneToManySaveConfig]:
    """Resolve editable one-to-many fields from a layout."""

    content_type = ContentType.objects.get_for_model(parent_model)
    item_ids = [
        item.id
        for row in layout.rows
        for item in row.items
        if str(item.id).isdigit()
    ]
    if not item_ids:
        return []

    application_fields = {
        field.pk: field
        for field in ApplicationField.objects.filter(content_type=content_type, id__in=item_ids)
    }

    configs: list[OneToManySaveConfig] = []
    for row in layout.rows:
        for item in row.items:
            if not str(item.id).isdigit():
                continue

            application_field = application_fields.get(int(item.id))
            if application_field is None:
                continue

            field_type = application_field.get_field_type_enum().value
            if field_type.id != "OneToManyField":
                continue

            if not permission_manager.has_field_permission(
                application_field,
                create_permission_str(parent_model, "change"),
            ):
                continue

            related_model = application_field.get_related_model()
            parent_fk_name = _resolve_parent_fk_name(application_field, parent_model, related_model)
            if related_model is None or parent_fk_name is None:
                continue

            editable_fields = _get_editable_related_fields(
                application_field=application_field,
                related_model=related_model,
                parent_fk_name=parent_fk_name,
                layout_config=item.config if isinstance(item.config, dict) else {},
                permission_manager=permission_manager,
            )
            if not editable_fields:
                continue

            configs.append(
                OneToManySaveConfig(
                    application_field=application_field,
                    related_model=related_model,
                    parent_fk_name=parent_fk_name,
                    editable_fields=editable_fields,
                )
            )

    return configs


def _save_one_to_many_field(
    *,
    parent_object: models.Model,
    config: OneToManySaveConfig,
    submitted_data: Mapping[str, Any],
    permission_manager: UserPermissionManager,
) -> None:
    rows = _parse_submitted_rows(config.prefix, submitted_data)
    if not rows:
        return

    form_class = forms.modelform_factory(
        config.related_model,
        fields=[field.field for field in config.editable_fields],
    )

    for row_index, row_data in rows.items():
        instance = _get_row_instance(
            parent_object=parent_object,
            config=config,
            row_index=row_index,
            row_data=row_data,
            permission_manager=permission_manager,
        )
        is_new_row = instance is None

        if row_data.get(ROW_DELETE_KEY):
            _delete_row(instance=instance, config=config, permission_manager=permission_manager)
            continue

        if is_new_row and _is_blank_new_row(row_data, config.editable_fields):
            continue

        form = form_class(row_data, instance=instance)
        if not form.is_valid():
            raise ValidationError(_format_form_errors(config.application_field.title, row_index, form))

        child = form.save(commit=False)
        setattr(child, config.parent_fk_name, parent_object)
        _stamp_child(child, permission_manager.user)
        action = "add" if is_new_row else "change"
        _assert_can_save_child(
            child,
            action,
            form.cleaned_data,
            config,
            permission_manager,
        )
        child.save()
        if hasattr(form, "save_m2m"):
            form.save_m2m()


def _parse_submitted_rows(prefix: str, submitted_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    prefix_with_separator = f"{prefix}{ROW_KEY_SEPARATOR}"

    for key in submitted_data.keys():
        if not key.startswith(prefix_with_separator):
            continue

        parts = key.split(ROW_KEY_SEPARATOR, 2)
        if len(parts) != 3:
            continue

        _, row_index, field_name = parts
        rows.setdefault(row_index, {})[field_name] = _get_submitted_value(submitted_data, key)

    return rows


def _get_submitted_value(submitted_data: Mapping[str, Any], key: str) -> Any:
    if hasattr(submitted_data, "getlist"):
        values = submitted_data.getlist(key)
        if len(values) > 1:
            return values
    return submitted_data.get(key)


def _get_row_instance(
    *,
    parent_object: models.Model,
    config: OneToManySaveConfig,
    row_index: str,
    row_data: dict[str, Any],
    permission_manager: UserPermissionManager,
) -> models.Model | None:
    raw_pk = row_data.get(ROW_ID_KEY)
    if raw_pk in (None, ""):
        return None

    permission = create_permission_str(config.related_model, "change")
    queryset = permission_manager.get_queryset(config.related_model, permission)
    instance = queryset.filter(
        pk=raw_pk,
        **{config.parent_fk_name: parent_object},
    ).first()
    if instance is None:
        raise ValidationError(f"{config.application_field.title} row {row_index}: permission denied or row no longer exists.")
    return instance


def _delete_row(
    *,
    instance: models.Model | None,
    config: OneToManySaveConfig,
    permission_manager: UserPermissionManager,
) -> None:
    if instance is None:
        return

    permission = create_permission_str(config.related_model, "delete")
    if not permission_manager.has_access_to_object(instance, permission):
        raise ValidationError(f"{config.application_field.title}: you do not have permission to delete this row.")
    instance.delete()


def _is_blank_new_row(row_data: dict[str, Any], editable_fields: list[ApplicationField]) -> bool:
    for application_field in editable_fields:
        value = row_data.get(application_field.field)
        if value not in (None, "", []):
            return False
    return True


def _assert_can_save_child(
    child: models.Model,
    action: str,
    cleaned_data: dict[str, Any],
    config: OneToManySaveConfig,
    permission_manager: UserPermissionManager,
) -> None:
    permission = create_permission_str(config.related_model, action)
    if getattr(permission_manager.user, "is_superuser", False):
        return

    if action == "change":
        if not permission_manager.has_access_to_object(child, permission):
            raise ValidationError(f"{config.application_field.title}: you do not have permission to update this row.")
        return

    if not permission_manager.has_global_permission(config.related_model, permission):
        raise ValidationError(f"{config.application_field.title}: you do not have permission to add rows.")

    candidate_data = {
        **cleaned_data,
        config.parent_fk_name: getattr(child, config.parent_fk_name),
    }
    if not permission_manager.candidate_matches_row_policies(config.related_model, permission, candidate_data):
        raise ValidationError(f"{config.application_field.title}: this row does not match your create permissions.")


def _stamp_child(child: models.Model, user) -> None:
    if hasattr(child, "updated_by"):
        child.updated_by = user
    if child._state.adding and hasattr(child, "created_by") and not getattr(child, "created_by", None):
        child.created_by = user


def _get_editable_related_fields(
    *,
    application_field: ApplicationField,
    related_model: type[models.Model],
    parent_fk_name: str,
    layout_config: dict[str, Any],
    permission_manager: UserPermissionManager,
) -> list[ApplicationField]:
    content_type = ContentType.objects.get_for_model(related_model)
    configured_fields = [
        str(field_name)
        for field_name in layout_config.get("inline_fields", [])
        if str(field_name) != parent_fk_name
    ]
    related_fields_queryset = ApplicationField.objects.filter(content_type=content_type)
    if configured_fields:
        related_fields_queryset = related_fields_queryset.filter(field__in=configured_fields)
    else:
        related_fields_queryset = related_fields_queryset.order_by("field")

    related_fields = {field.field: field for field in related_fields_queryset}
    candidate_field_names = configured_fields or list(related_fields.keys())
    change_permission = create_permission_str(related_model, "change")
    editable_fields: list[ApplicationField] = []
    for field_name in candidate_field_names:
        related_field = related_fields.get(field_name)
        if related_field is None:
            continue
        if related_field.field == parent_fk_name:
            continue
        if not _is_model_editable_field(related_field):
            continue
        if not permission_manager.has_field_permission(related_field, change_permission):
            continue
        editable_fields.append(related_field)
        if not configured_fields and len(editable_fields) >= 6:
            break

    return editable_fields


def _is_model_editable_field(application_field: ApplicationField) -> bool:
    try:
        model_field = application_field._get_model_field()
    except Exception:
        return False
    if getattr(model_field, "auto_created", False):
        return False
    if not getattr(model_field, "editable", True):
        return False
    if not getattr(model_field, "concrete", True):
        return False
    try:
        return application_field.get_form_field() is not None
    except Exception:
        return False


def _resolve_parent_fk_name(
    application_field: ApplicationField,
    parent_model: type[models.Model],
    related_model: type[models.Model] | None,
) -> str | None:
    if related_model is None:
        return None

    try:
        relation = application_field._get_model_field()
    except Exception:
        relation = None

    relation_field = getattr(relation, "field", None)
    if relation_field is not None and getattr(relation_field.remote_field, "model", None) == parent_model:
        return relation_field.name

    for model_field in related_model._meta.fields:
        remote_field = getattr(model_field, "remote_field", None)
        if getattr(remote_field, "model", None) == parent_model:
            return model_field.name
    return None


def _format_form_errors(field_title: str, row_index: str, form: forms.Form) -> list[str]:
    errors: list[str] = []
    for field_name, field_errors in form.errors.items():
        label = form.fields.get(field_name).label if field_name in form.fields else field_name
        for error in field_errors:
            errors.append(f"{field_title} row {row_index}, {label}: {error}")
    return errors


def _flatten_validation_error(error: ValidationError) -> list[str]:
    if hasattr(error, "error_list"):
        return [str(item.message) for item in error.error_list]
    return [str(error)]
