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
    widget = application_field.get_widget()

    # TODO: get rid of the "select" and get choices stuff because it's too much coupling
    widget_choices = getattr(widget, "get_choices", lambda *_args, **_kwargs: [])()
    is_select_widget = isinstance(widget, forms.Select) or bool(widget_choices)

    attrs = {
        "class": "select w-full" if is_select_widget else "input w-full",
    }
    if not can_edit:
        attrs["disabled"] = "disabled" if is_select_widget else "readonly"

    input_html = widget.render(
        name=application_field.field,
        value=value,
        attrs=attrs,
    )
    return {
        "value": value,
        "object": obj,
        "application_field": application_field,
        "input": input_html,
    }


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


def get_available_detail_fields(*, content_type: ContentType, user) -> list[dict[str, Any]]:
    model = content_type.model_class()
    permission_manager = UserPermissionManager(user)
    permission_str = f"view_{model._meta.model_name}"

    fields = ApplicationField.objects.filter(content_type=content_type).order_by("field")
    available: list[dict[str, Any]] = []

    for field in fields:
        if not permission_manager.has_field_permission(field, permission_str):
            continue
        available.append(
            {
                "id": field.pk,
                "title": field.title,
                "description": field.field,
                "icon": "fa-table-cells-large",
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



def resolve_field(field_name:str, model_or_content_type:Type[Model]|ContentType, queryset:Optional[QuerySet[ApplicationField]]) -> ApplicationField:
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

    field_queryset = queryset if queryset is not None else ApplicationField.objects.all(content_type=content_type)

    application_field = (
        field_queryset.filter(field=field_name).order_by("pk").first()
        or field_queryset.filter(field__iexact=field_name).order_by("pk").first()
    )

    if application_field is None:
        raise ApplicationField.DoesNotExist(
            f"No ApplicationField found for field='{field_name}' and content_type='{content_type}'."
        )

    return application_field


def create_default_layout(model:Type[Model]) -> FieldLayout:
    """
    Creates a default field layout based on the given model.
    """
    content_type = ContentType.objects.get_for_model(model)
    application_fields = ApplicationField.objects.filter(content_type=content_type).order_by("field")
    model_layout = get_model_field_layout(model)

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
