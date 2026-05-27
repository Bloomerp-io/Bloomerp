

import json

from django.http import Http404, HttpRequest, HttpResponse
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.user_create_view_preference import UserCreateViewPreference
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, render
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    get_object_field_value,
)
from bloomerp.services.workspace_services import render_tile_to_string


def _tile(request: HttpRequest, content_type: ContentType) -> HttpResponse:
    tile_id = request.GET.get("tile_id")
    if not tile_id:
        return HttpResponse(status=404)

    tile = Tile.objects.get(id=tile_id)
    try:
        colspan = max(1, int(request.GET.get("colspan", 1)))
    except (TypeError, ValueError):
        colspan = 1
    try:
        max_cols = max(1, int(request.GET.get("max_cols", 4)))
    except (TypeError, ValueError):
        max_cols = 4

    error = False
    try:
        content = render_tile_to_string(tile, request.user)
    except Exception as e:
        content = e
        error = True

    context = {
        "icon": tile.icon,
        "title": tile.name,
        "description": tile.description,
        "content": content,
        "tile_id": tile.id,
        "colspan": colspan,
        "max_cols": max_cols,
        "tile_type": tile.type.lower(),
        "tile_search_keywords": tile.get_type_display(),
    }
    return render(request, "components/workspaces/render_workspace_tile.html", context=context)


def _get_request_layout_config(request: HttpRequest) -> dict:
    try:
        config = json.loads(request.GET.get("config", "{}"))
    except json.JSONDecodeError:
        return {}
    return config if isinstance(config, dict) else {}


def _render_application_field(request: HttpRequest, content_type: ContentType) -> HttpResponse:
    model_content_type_id = request.GET.get("content_type_id")
    if not model_content_type_id:
        return HttpResponse("Missing content_type_id", status=400)

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

    context["colspan"] = request.GET.get("colspan", 1)
    if "non_required_fields_visible" in request.GET:
        context["non_required_fields_visible"] = request.GET.get("non_required_fields_visible")
    return render(request, "inclusion_tags/layout_field.html", context)


def _build_create_render_context(*, request: HttpRequest, content_type: ContentType, model, application_field: ApplicationField):
    manager = UserPermissionManager(request.user)
    if not manager.has_global_permission(
        model,
        create_permission_str(model, "add"),
    ):
        return HttpResponse("Permission denied", status=403)

    field_type = application_field.get_field_type_enum().value
    addable_fields = list(get_addable_fields(content_type=content_type, user=request.user))
    allowed_field_names = [field.field for field in addable_fields]
    if field_type.allow_in_model and application_field.field not in allowed_field_names:
        return HttpResponse("Permission denied", status=403)

    if not field_type.allow_in_model:
        if not field_type.editable_without_form_field:
            return HttpResponse("Permission denied", status=403)
        return build_crud_layout_field_context(
            application_field=application_field,
            value=None,
            can_edit=True,
            layout_config=_get_request_layout_config(request),
        )

    form_class = bloomerp_modelform_factory(model_cls=model, fields=allowed_field_names)
    form = form_class()
    if application_field.field not in form.fields:
        return HttpResponse("Unknown field", status=400)

    return build_crud_layout_field_context(
        application_field=application_field,
        bound_field=form[application_field.field],
        layout_config=_get_request_layout_config(request),
    )


def _build_detail_render_context(*, request: HttpRequest, model, application_field: ApplicationField, object_id: str):
    permission_manager = UserPermissionManager(request.user)
    view_permission = create_permission_str(model, "view")
    allowed_queryset = permission_manager.get_queryset(model, view_permission)
    obj = get_object_or_404(allowed_queryset, pk=object_id)
    return build_crud_layout_field_context(
        application_field=application_field,
        value=get_object_field_value(obj=obj, application_field=application_field),
        can_edit=permission_manager.has_field_permission(application_field, create_permission_str(model, "change")),
        layout_config=_get_request_layout_config(request),
    )


items = {
    Workspace: _tile,
    UserDetailViewPreference: _render_application_field,
    UserCreateViewPreference: _render_application_field,
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
