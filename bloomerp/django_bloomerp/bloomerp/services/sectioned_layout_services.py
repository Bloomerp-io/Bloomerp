import json
from dataclasses import dataclass
from typing import Any, Optional, Type

from django.contrib.contenttypes.models import ContentType
from django import forms
from django.forms import BoundField
from django.db.models import Model

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.models import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.manager import UserPolicyManager
from django.db.models import QuerySet
from django.utils.translation import gettext

MAX_LAYOUT_COLUMNS = 12

@dataclass
class AvailableLayoutItem:
    id:str
    title:str
    description:str
    icon:str
    search_keywords: str = ""

def clamp_layout_columns(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(MAX_LAYOUT_COLUMNS, parsed))


def clamp_layout_colspan(value: Any, max_columns: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(max(1, max_columns), parsed))


def normalize_layout_payload(payload: dict[str, Any] | FieldLayout | None) -> FieldLayout:
    raw_rows = []
    if isinstance(payload, FieldLayout):
        raw_rows = payload.model_dump().get("rows", [])
    elif isinstance(payload, dict):
        raw_rows = payload.get("rows", [])

    rows: list[LayoutRow] = []
    seen_item_ids: set[int | str] = set()
    if isinstance(raw_rows, list):
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue

            columns = clamp_layout_columns(raw_row.get("columns"))
            title = raw_row.get("title")
            if not isinstance(title, str):
                title = None
            elif not title.strip():
                title = None
            else:
                title = title.strip()

            items: list[LayoutItem] = []
            raw_items = raw_row.get("items", [])
            if isinstance(raw_items, list):
                for raw_item in raw_items:
                    if not isinstance(raw_item, dict):
                        continue
                    item_id = raw_item.get("id")
                    if item_id in (None, ""):
                        continue
                    normalized_item_id = str(item_id).strip()
                    if not normalized_item_id:
                        continue
                    if normalized_item_id in seen_item_ids:
                        continue
                    seen_item_ids.add(normalized_item_id)
                    config = raw_item.get("config", {})
                    if not isinstance(config, dict):
                        config = {}
                    items.append(
                        LayoutItem(
                            id=normalized_item_id,
                            colspan=clamp_layout_colspan(raw_item.get("colspan"), columns),
                            config=config,
                        )
                    )

            rows.append(LayoutRow(columns=columns, title=title, items=items))

    if not rows:
        rows = [LayoutRow(columns=1, title=None, items=[])]

    return FieldLayout(rows=rows)


def serialize_layout(layout: FieldLayout | dict[str, Any] | None) -> dict[str, Any]:
    return normalize_layout_payload(layout).model_dump()


def dump_layout_json(layout: FieldLayout | dict[str, Any] | None) -> str:
    return json.dumps(serialize_layout(layout))


def layout_has_items(layout: FieldLayout | dict[str, Any] | None) -> bool:
    normalized = normalize_layout_payload(layout)
    return any(row.items for row in normalized.rows)


def get_model_field_layout(model: Type[Model]) -> FieldLayout | None:
    bloomerp_config = getattr(model, "bloomerp_config", None)
    detail_view_settings = (
        getattr(bloomerp_config, "detail_view_settings", None)
        if bloomerp_config is not None
        else None
    )
    if detail_view_settings is not None:
        default_layout = detail_view_settings.get_default_layout()
        if default_layout is not None:
            return normalize_layout_payload(default_layout)

    legacy_layout = getattr(model, "field_layout", None)
    if legacy_layout:
        return normalize_layout_payload(legacy_layout)

    return None


def get_object_field_value(*, obj: Model, application_field: ApplicationField) -> Any:
    value = getattr(obj, application_field.field, None)
    try:
        model_field = application_field._get_model_field()
    except Exception:
        model_field = None

    if value is None and model_field is not None:
        accessor_name = getattr(model_field, "get_accessor_name", lambda: None)()
        if accessor_name:
            value = getattr(obj, accessor_name, None)

    return value


def _get_readonly_layout_widget_attrs(*, widget: forms.Widget) -> dict[str, str]:
    attrs = get_layout_widget_attrs(widget=widget)
    # Readonly HTML inputs still submit their value on POST. Disabled widgets stay
    # visible in the overview while being excluded from form submission.
    attrs["disabled"] = "disabled"
    if not isinstance(widget, forms.Select):
        attrs["readonly"] = "readonly"
    return attrs


def build_crud_layout_field_context(
    *,
    application_field: ApplicationField,
    bound_field: BoundField | None = None,
    value: Any = None,
    can_edit: bool = True,
    layout_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout_config = layout_config or {}
    if bound_field is not None:
        widget = bound_field.field.widget
        attrs = get_layout_widget_attrs(widget=widget)
        if bound_field.errors:
            attrs["class"] += " border-red-500"

        return build_layout_field_context(
            application_field=application_field,
            value=bound_field.value(),
            input=bound_field.as_widget(attrs=attrs),
            help_text=bound_field.help_text,
            errors=list(bound_field.errors),
            field=bound_field,
            config=layout_config,
        )

    widget = application_field.get_widget(layout_config=layout_config)
    attrs = get_layout_widget_attrs(widget=widget) if can_edit else _get_readonly_layout_widget_attrs(widget=widget)
    return build_layout_field_context(
        application_field=application_field,
        value=value,
        input=widget.render(
            name=application_field.field,
            value=value,
            attrs=attrs,
        ),
        help_text=get_application_field_help_text(application_field),
        config=layout_config,
    )


def resolve_detail_layout_rows(
    *,
    layout: FieldLayout | dict[str, Any] | None,
    content_type: ContentType,
    user,
) -> list[dict[str, Any]]:
    manager = UserPolicyManager(user)
    model = content_type.model_class()
    permission_str = f"view_{model._meta.model_name}"
    change_permission_str = f"change_{model._meta.model_name}"

    normalized = normalize_layout_payload(layout)
    rows: list[dict[str, Any]] = []

    for row in normalized.rows:
        resolved_items: list[dict[str, Any]] = []
        for item in row.items:
            application_field = ApplicationField.objects.filter(
                id=item.id,
                content_type=content_type,
            ).first()
            if not application_field:
                continue

            can_view = manager.has_field_permission(application_field, permission_str)
            if not can_view:
                continue

            resolved_items.append(
                {
                    "id": application_field.pk,
                    "colspan": clamp_layout_colspan(item.colspan, row.columns),
                    "application_field": application_field,
                    "can_view": can_view,
                    "can_edit": manager.has_field_permission(application_field, change_permission_str),
                }
            )

        rows.append(
            {
                "title": gettext(row.title) if row.title else row.title,
                "columns": row.columns,
                "items": resolved_items,
            }
        )

    return rows


def get_layout_widget_attrs(*, widget: forms.Widget) -> dict[str, str]:
    """Style layout widgets while preserving compact checkbox controls."""
    if isinstance(widget, forms.CheckboxInput):
        return {"class": "h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"}
    choices_getter = getattr(widget, "get_choices", None)
    widget_choices = choices_getter() if choices_getter else getattr(widget, "choices", [])
    is_select_widget = isinstance(widget, forms.Select) or bool(widget_choices)
    return {
        "class": "select w-full" if is_select_widget else "input w-full",
    }


def get_application_field_help_text(application_field: ApplicationField) -> str:
    """Return the form help text configured for an application field."""
    # TODO: In the future it would be nice to save description on the actual application field
    form_field = application_field.get_form_field()
    if form_field is None:
        return ""
    return form_field.help_text or ""


def get_application_field_is_required(application_field: ApplicationField) -> bool:
    """Return whether an application field should be marked as required in CRUD layouts."""
    # TODO: In the future we want to save whether the field is required on the actual application field
    form_field = application_field.get_form_field()
    if form_field is None:
        return False
    return bool(getattr(form_field, "required", False))


def build_layout_field_context(
    *,
    application_field: ApplicationField,
    value: Any,
    input: str,
    help_text: str = "",
    errors: Optional[list[str]] = None,
    field=None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or {}
    return {
        "value": value,
        "application_field": application_field,
        "display_label": str(config.get("label") or application_field.title),
        "field": field,
        "input": input,
        "help_text": help_text,
        "errors": errors or [],
        "config": config,
        "config_json": json.dumps(config),
        "is_required": bool(getattr(field, "field", None) and field.field.required) if field is not None else get_application_field_is_required(application_field),
    }


def get_available_layout_fields(*, content_type: ContentType, user, layout_kind: str) -> list[dict[str, Any]]:
    """
    Returns the available fields for a particular content type
    and user.
    """
    # TODO: use dataclass for response here
    model = content_type.model_class()
    permission_manager = UserPolicyManager(user)
    permission_prefix = "add" if layout_kind == "create" else "view"
    permission_str = f"{permission_prefix}_{model._meta.model_name}"

    fields = ApplicationField.objects.filter(content_type=content_type).order_by("field")
    available: list[dict[str, Any]] = []
    for field in fields:
        if not permission_manager.has_field_permission(field, permission_str):
            continue

        field_type = field.get_field_type()

        available.append(
            {
                "id": field.pk,
                "title": field.title,
                "description": field_type.label,
                "icon": field_type.icon,
                "is_required": get_application_field_is_required(field),
            }
        )
    return available


def resolve_field(
    field_name: str,
    model_or_content_type: Type[Model] | ContentType,
    queryset: Optional[QuerySet[ApplicationField] | list[ApplicationField]],
) -> ApplicationField:
    """
    Resolves a field to an ApplicationField based on the field name (field attribute).
    I.e. if the field name is first name, it will return the first name
    application field. This can be used for the field layout
    """
    if not field_name or not isinstance(field_name, str):
        raise ValueError("field_name must be a non-empty string")

    if isinstance(model_or_content_type, ContentType):
        content_type = model_or_content_type
    else:
        content_type = ContentType.objects.get_for_model(model_or_content_type)

    field_queryset = queryset if queryset is not None else ApplicationField.objects.filter(content_type=content_type)

    if isinstance(field_queryset, QuerySet):
        application_field = (
            field_queryset.filter(field=field_name).order_by("pk").first()
            or field_queryset.filter(field__iexact=field_name).order_by("pk").first()
        )
    else:
        application_field = next(
            (
                field
                for field in sorted(field_queryset, key=lambda application_field: application_field.pk)
                if field.field == field_name or field.field.lower() == field_name.lower()
            ),
            None,
        )

    if application_field is None:
        raise ApplicationField.DoesNotExist(
            f"No ApplicationField found for field='{field_name}' and content_type='{content_type}'."
        )

    return application_field


def create_default_layout(
    model: Type[Model],
    application_fields: QuerySet[ApplicationField] | list[ApplicationField] | None = None,
    *,
    layout: FieldLayout | None = None,
) -> FieldLayout:
    """
    Creates a default field layout based on the given model.
    """
    content_type = ContentType.objects.get_for_model(model)
    if application_fields is None:
        application_fields = ApplicationField.objects.filter(content_type=content_type).order_by("field")

    if isinstance(application_fields, QuerySet):
        application_fields = list(application_fields.order_by("field"))
    else:
        application_fields = sorted(application_fields, key=lambda field: field.field)

    available_field_ids = {application_field.pk for application_field in application_fields}
    model_layout = layout if layout is not None else get_model_field_layout(model)

    if model_layout:
        rows: list[LayoutRow] = []
        for row in model_layout.rows:
            resolved_items: list[LayoutItem] = []
            for item in row.items:
                resolved_id = item.id
                if isinstance(resolved_id, str):
                    try:
                        resolved_id = resolve_field(resolved_id, model, application_fields).pk
                    except ApplicationField.DoesNotExist:
                        continue

                if resolved_id not in available_field_ids:
                    continue
                resolved_items.append(
                    LayoutItem(
                        id=resolved_id,
                        colspan=clamp_layout_colspan(item.colspan, row.columns),
                        config=item.config,
                    )
                )

            rows.append(
                LayoutRow(
                    columns=row.columns,
                    title=row.title,
                    items=resolved_items,
                )
            )

        return FieldLayout(rows=rows)

    else:
        items = [
            LayoutItem(id=application_field.pk, colspan=1)
            for application_field in application_fields
            if application_field.get_field_type() != FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD
            and application_field.field not in [
                "id", 
                "pk", 
                "updated_by", 
                "created_by",
                "datetime_created",
                "datetime_updated",
                "comments"
            ]
        ]
        return FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    title="Details",
                    items=items,
                )
            ]
        )
