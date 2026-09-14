

import json

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import LayoutItem
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render
from bloomerp.forms.model_form import (
    bloomerp_modelform_factory,
    get_model_form_application_fields,
)
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    get_object_field_value,
)
from bloomerp.services.workspace_services import build_workspace_layout_item

# TODO: Permission checks and caching required
def _tile(request: HttpRequest, content_type: ContentType) -> HttpResponse:
    tile_id = request.GET.get("tile_id")
    if not tile_id:
        return HttpResponse(status=404)

    tile = get_object_or_404(Tile, id=tile_id)
    try:
        colspan = max(1, int(request.GET.get("colspan", 1)))
    except (TypeError, ValueError):
        colspan = 1
    try:
        max_cols = min(12, max(1, int(request.GET.get("max_cols", 4))))
    except (TypeError, ValueError):
        max_cols = 4
    try:
        config = json.loads(request.GET.get("config", "{}"))
    except json.JSONDecodeError:
        return HttpResponse("Invalid layout item config", status=400)
    if not isinstance(config, dict):
        return HttpResponse("Invalid layout item config", status=400)
    item = build_workspace_layout_item(
        tile=tile,
        request=request,
        colspan=colspan,
        config=config,
        workspace_id=request.GET.get("workspace_id"),
    )
    item.extra_attrs = {
        **(item.extra_attrs or {}),
        "data-max-cols": str(max_cols),
    }
    return render(
        request,
        "cotton/features/layout/item.html",
        context={"item": item},
    )


def _get_request_layout_config(request: HttpRequest, content_type: ContentType) -> dict:
    layout_object_id = request.GET.get("layout_object_id")
    field_id = request.GET.get("field_id")
    layout_model = content_type.model_class()
    if layout_object_id and field_id and layout_model in {Form, UserObjectLayoutPreference}:
        layout_object = get_object_or_404(layout_model, pk=layout_object_id)
        for row in layout_object.layout_obj.rows:
            for item in row.items:
                if str(item.id) == field_id:
                    return item.config if isinstance(item.config, dict) else {}

    try:
        config = json.loads(request.GET.get("config", "{}"))
    except json.JSONDecodeError:
        return {}
    return config if isinstance(config, dict) else {}


def _get_layout_item(request: HttpRequest, content_type: ContentType, field_id: str) -> LayoutItem | None:
    layout_object_id = request.GET.get("layout_object_id")
    layout_model = content_type.model_class()
    if not layout_object_id or layout_model not in {Form, UserObjectLayoutPreference}:
        return None

    layout_object = get_object_or_404(layout_model, pk=layout_object_id)
    return next(
        (
            item
            for row in layout_object.layout_obj.rows
            for item in row.items
            if str(item.id) == field_id
        ),
        None,
    )


def _render_application_field(request: HttpRequest, content_type: ContentType) -> HttpResponse:
    model_content_type_id = request.GET.get(
        "target_content_type_id"
    ) or request.GET.get("content_type_id")
    if not model_content_type_id:
        return HttpResponse("Missing target_content_type_id", status=400)

    model_content_type = get_object_or_404(ContentType, id=model_content_type_id)
    model = model_content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    field_id = request.GET.get("field_id")
    if not field_id:
        return HttpResponse("Missing field_id", status=400)

    application_field = get_object_or_404(ApplicationField, pk=field_id, content_type=model_content_type)
    object_id = request.GET.get("object_id")

    if object_id:
        context = _build_detail_render_context(
            request=request,
            content_type=content_type,
            model=model,
            application_field=application_field,
            object_id=object_id,
        )
    else:
        context = _build_create_render_context(
            request=request,
            content_type=model_content_type,
            model=model,
            application_field=application_field,
        )

    if isinstance(context, HttpResponse):
        return context

    layout_item = _get_layout_item(request, content_type, field_id)
    config = layout_item.config if layout_item is not None else context["config"]
    item = LayoutItem(
        id=application_field.pk,
        colspan=layout_item.colspan if layout_item is not None else request.GET.get("colspan", 1),
        config=config,
        label=context["display_label"],
        content=render_to_string("inclusion_tags/layout_field_content.html", context, request=request),
        component_name="detail-view-value",
        edit_url=(
            reverse(
                "components_field_display_options",
                kwargs={"application_field_id": application_field.pk},
            )
            + f"?layout_object_content_type_id={content_type.pk}&layout_object_id={request.GET.get('layout_object_id')}"
            if layout_item is not None and application_field.get_field_type().display_options
            else None
        ),
    )
    if "non_required_fields_visible" in request.GET:
        item.is_visible = request.GET.get("non_required_fields_visible") == "true" or context["is_required"] or bool(context["errors"])
    return render(
        request,
        "cotton/features/layout/item.html",
        {"item": item, "layout_edit_mode": True},
    )


def _build_create_render_context(*, request: HttpRequest, content_type: ContentType, model, application_field: ApplicationField):
    manager = UserPolicyManager(request.user)
    if not manager.has_global_permission(
        model,
        create_permission_str(model, "add"),
    ):
        return HttpResponse("Permission denied", status=403)

    accessible_fields = manager.get_accessible_fields(
        content_type,
        create_permission_str(model, "add"),
    )
    form_application_fields = get_model_form_application_fields(
        model,
        accessible_fields,
    )
    allowed_field_names = list(
        form_application_fields.values_list("field", flat=True)
    )
    if application_field.field not in allowed_field_names:
        return HttpResponse("Permission denied", status=403)

    form_class = bloomerp_modelform_factory(model_cls=model, fields=allowed_field_names)
    form = form_class()
    if application_field.field not in form.fields:
        return HttpResponse("Unknown field", status=400)

    return build_crud_layout_field_context(
        application_field=application_field,
        bound_field=form[application_field.field],
        layout_config=_get_request_layout_config(request, content_type),
    )


def _build_detail_render_context(
    *,
    request: HttpRequest,
    content_type: ContentType,
    model,
    application_field: ApplicationField,
    object_id: str,
):
    permission_manager = UserPolicyManager(request.user)
    view_permission = create_permission_str(model, "view")
    allowed_queryset = permission_manager.get_queryset(model, view_permission)
    obj = get_object_or_404(allowed_queryset, pk=object_id)
    viewable_fields = permission_manager.get_accessible_fields_for_object(
        obj,
        view_permission,
    )
    if not viewable_fields.filter(pk=application_field.pk).exists():
        return HttpResponse("Permission denied", status=403)

    changeable_fields = permission_manager.get_accessible_fields_for_object(
        obj,
        create_permission_str(model, "change"),
    )
    return build_crud_layout_field_context(
        application_field=application_field,
        value=get_object_field_value(obj=obj, application_field=application_field),
        can_edit=changeable_fields.filter(pk=application_field.pk).exists(),
        layout_config=_get_request_layout_config(request, content_type),
    )


items = {
    Workspace: _tile,
    Form: _render_application_field,
    UserObjectLayoutPreference: _render_application_field,
}


@router.register(
    path="components/layout/render-layout-item/<int:content_type_id>/",
    name="components_render_layout_item"
)
def render_layout_item(
    request: HttpRequest,
    content_type_id: int,
) -> HttpResponse:
    """Renders a layout item based on the content type ID"""
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)

    content_type: ContentType = get_object_or_404(ContentType, id=content_type_id)

    func = items.get(content_type.model_class())

    if not func:
        return HttpResponse(status=404)

    return func(request, content_type)
