import json
from typing import Any, Optional, Type

from django.contrib.contenttypes.models import ContentType
from django import forms
from django.db.models import Model

from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.application_field import ApplicationField
from bloomerp.services.permission_services import UserPermissionManager
from django.db.models import QuerySet

MAX_LAYOUT_COLUMNS = 12


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
                    normalized_item_id = int(item_id) if str(item_id).isdigit() else item_id
                    if normalized_item_id in seen_item_ids:
                        continue
                    seen_item_ids.add(normalized_item_id)
                    items.append(
                        LayoutItem(
                            id=normalized_item_id,
                            colspan=clamp_layout_colspan(raw_item.get("colspan"), columns),
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
    bloomerp_config = getattr(model, "Bloomerp", None)
    if bloomerp_config is not None:
        bloomerp_layout = getattr(bloomerp_config, "field_layout", None)
        if bloomerp_layout:
            return normalize_layout_payload(bloomerp_layout)

    legacy_layout = getattr(model, "field_layout", None)
    if legacy_layout:
        return normalize_layout_payload(legacy_layout)

    return None


def get_default_workspace_layout() -> FieldLayout:
    return FieldLayout(
        rows=[
            LayoutRow(
                title="Highlights",
                columns=4,
                items=[
                    LayoutItem(id=9001, colspan=1),
                    LayoutItem(id=9002, colspan=2),
                    LayoutItem(id=9004, colspan=1),
                ],
            ),
            LayoutRow(
                title="Pipeline",
                columns=4,
                items=[
                    LayoutItem(id=9003, colspan=3),
                    LayoutItem(id=9005, colspan=2),
                ],
            ),
            LayoutRow(
                title="Resources",
                columns=4,
                items=[
                    LayoutItem(id=9006, colspan=4),
                    LayoutItem(id=9007, colspan=4),
                ],
            ),
        ]
    )


def build_detail_value_context(
    *,
    obj: Model,
    application_field: ApplicationField,
    can_edit: bool,
) -> dict[str, Any]:
    value = getattr(obj, application_field.field, None)
    try:
        model_field = application_field._get_model_field()
    except Exception:
        model_field = None

    if value is None and model_field is not None:
        accessor_name = getattr(model_field, "get_accessor_name", lambda: None)()
        if accessor_name:
            value = getattr(obj, accessor_name, None)

    widget = application_field.get_widget()
    attrs = get_layout_widget_attrs(widget=widget)
    if not can_edit:
        attrs["disabled" if isinstance(widget, forms.Select) else "readonly"] = "disabled" if isinstance(widget, forms.Select) else "readonly"

    input_html = widget.render(
        name=application_field.field,
        value=value,
        attrs=attrs,
    )
    return build_layout_field_context(
        application_field=application_field,
        value=value,
        input=input_html,
        help_text=get_application_field_help_text(application_field),
    )


def resolve_detail_layout_rows(
    *,
    layout: FieldLayout | dict[str, Any] | None,
    content_type: ContentType,
    user,
) -> list[dict[str, Any]]:
    manager = UserPermissionManager(user)
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
                "title": row.title,
                "columns": row.columns,
                "items": resolved_items,
            }
        )

    return rows


def build_create_field_context(
    *,
    form,
    application_field: ApplicationField,
) -> dict[str, Any]:
    bound_field = form[application_field.field]
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
    )


def resolve_create_layout_rows(
    *,
    layout: FieldLayout | dict[str, Any] | None,
    content_type: ContentType,
    user,
    form,
) -> list[dict[str, Any]]:
    manager = UserPermissionManager(user)
    model = content_type.model_class()
    permission_str = f"add_{model._meta.model_name}"

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
            if application_field.field not in form.fields:
                continue
            if not manager.has_field_permission(application_field, permission_str):
                continue

            resolved_items.append(
                {
                    "id": application_field.pk,
                    "colspan": clamp_layout_colspan(item.colspan, row.columns),
                    "application_field": application_field,
                    **build_create_field_context(
                        form=form,
                        application_field=application_field,
                    ),
                }
            )

        rows.append(
            {
                "title": row.title,
                "columns": row.columns,
                "items": resolved_items,
            }
        )

    return rows


def get_layout_widget_attrs(*, widget: forms.Widget) -> dict[str, str]:
    widget_choices = getattr(widget, "get_choices", lambda *_args, **_kwargs: getattr(widget, "choices", []))()
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
) -> dict[str, Any]:
    return {
        "value": value,
        "application_field": application_field,
        "field": field,
        "input": input,
        "help_text": help_text,
        "errors": errors or [],
        "is_required": bool(getattr(field, "field", None) and field.field.required) if field is not None else get_application_field_is_required(application_field),
    }


def get_available_layout_fields(*, content_type: ContentType, user, layout_kind: str) -> list[dict[str, Any]]:
    """
    Returns the available fields for a particular content type
    and user.
    """
    model = content_type.model_class()
    permission_manager = UserPermissionManager(user)
    permission_prefix = "add" if layout_kind == "create" else "view"
    permission_str = f"{permission_prefix}_{model._meta.model_name}"

    fields = ApplicationField.objects.filter(content_type=content_type).order_by("field")
    available: list[dict[str, Any]] = []
    for field in fields:
        if not permission_manager.has_field_permission(field, permission_str):
            continue
        
        field_type = field.get_field_type_enum().value
        if not field_type.allow_in_model:
            continue

        available.append(
            {
                "id": field.pk,
                "title": field.title,
                "description": field_type.display_name,
                "icon": field_type.icon,
            }
        )
    return available


def get_available_workspace_tiles() -> list[dict[str, Any]]:
    from bloomerp.components.workspaces.render_workspace_tile import DUMMY_TILES
    from bloomerp.models.workspaces.tile import Tile

    dummy_items = [
        {
            "id": tile.tile_id,
            "title": tile.title,
            "description": "Demo tile",
            "icon": tile.icon,
        }
        for tile in DUMMY_TILES.values()
    ]

    real_items = [
        {
            "id": tile.pk,
            "title": tile.name,
            "description": tile.description or "",
            "icon": "fa-grip",
        }
        for tile in Tile.objects.order_by("name")
    ]

    return dummy_items + real_items



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
    model_layout = get_model_field_layout(model)

    if model_layout:
        rows: list[LayoutRow] = []
        seen_field_ids: set[int] = set()
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
                seen_field_ids.add(resolved_id)
                resolved_items.append(
                    LayoutItem(
                        id=resolved_id,
                        colspan=clamp_layout_colspan(item.colspan, row.columns),
                    )
                )

            rows.append(
                LayoutRow(
                    columns=row.columns,
                    title=row.title,
                    items=resolved_items,
                )
            )

        remaining_items = [
            LayoutItem(id=application_field.pk, colspan=1)
            for application_field in application_fields
            if application_field.pk not in seen_field_ids
        ]
        if remaining_items:
            rows.append(
                LayoutRow(
                    columns=2,
                    title="Details",
                    items=remaining_items,
                )
            )

        return FieldLayout(rows=rows)

    else:
        items = [
            LayoutItem(id=application_field.pk, colspan=1)
            for application_field in application_fields
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
