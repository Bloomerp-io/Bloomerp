

import json

from django.contrib.contenttypes.models import ContentType
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from bloomerp.models import UserCreateViewPreference
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.models.workspaces.tile import Tile
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.services.permission_services import create_permission_str
from bloomerp.services.sectioned_layout_services import (
    get_available_layout_fields,
    normalize_layout_payload,
)



def _get_preference_model(*, scope: str):
    return UserCreateViewPreference if scope == "create" else UserDetailViewPreference

def _get_valid_field_ids(request: HttpRequest, *, content_type: ContentType, scope: str) -> set[str]:
    return {
        str(item["id"])
        for item in get_available_layout_fields(
            content_type=content_type,
            user=request.user,
            layout_kind=scope,
        )
    }

def _save_layout_preference(
    request: HttpRequest,
    *,
    payload: dict,
    content_type: ContentType,
    model,
    scope: str,
) -> HttpResponse:
    if payload.get("content_type_id") and str(payload.get("content_type_id")) != str(content_type.id):
        return HttpResponse("content_type_id does not match route", status=400)

    permission = create_permission_str(model, "add" if scope == "create" else "view")
    if not request.user.has_perm(f"{model._meta.app_label}.{permission}"):
        return HttpResponse("Permission denied", status=403)

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = _get_valid_field_ids(request, content_type=content_type, scope=scope)
    submitted_ids = {str(item.id) for row in layout.rows for item in row.items}
    if not submitted_ids.issubset(valid_ids):
        invalid_ids = sorted(submitted_ids - valid_ids)
        return JsonResponse(
            {"error": "Unknown field id in layout", "invalid_ids": invalid_ids},
            status=400,
        )

    preference_model = _get_preference_model(scope=scope)
    preference = preference_model.get_or_create_for_user(request.user, content_type)
    preference.field_layout = layout.model_dump()
    preference.save(update_fields=["field_layout"])
    return JsonResponse({"status": "ok", "layout": layout.model_dump()})

# ---------------------------------------------------------------------------
# Callables
# ---------------------------------------------------------------------------
def _save_workspace(request: HttpRequest, workspace: Workspace, payload: dict) -> dict:
    if workspace.user_id != request.user.id:
        return {"status": "error", "message": "Permission denied"}

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = {str(tile_id) for tile_id in Tile.objects.values_list("id", flat=True)}
    requested_ids = {str(item.id) for row in layout.rows for item in row.items}
    if not requested_ids.issubset(valid_ids):
        return {"status": "error", "message": "Unknown tile id in layout"}

    workspace.layout = layout.model_dump()
    workspace.save(update_fields=["layout"])
    return {"status": "ok", "layout": layout.model_dump()}

def _save_user_detail_view_preference(
    request: HttpRequest,
    preference: UserDetailViewPreference,
    payload: dict,
) -> HttpResponse:
    content_type = preference.content_type
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)
    return _save_layout_preference(
        request,
        payload=payload,
        content_type=content_type,
        model=model,
        scope="detail",
    )

def _save_user_create_view_preference(
    request: HttpRequest,
    preference: UserCreateViewPreference,
    payload: dict,
) -> HttpResponse:
    content_type = preference.content_type
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)
    return _save_layout_preference(
        request,
        payload=payload,
        content_type=content_type,
        model=model,
        scope="create",
    )

CALLABLES = {
    Workspace: _save_workspace,
    UserDetailViewPreference : _save_user_detail_view_preference,
    UserCreateViewPreference : _save_user_create_view_preference
}


@router.register(
    path="components/layout/save-layout-object/<int:content_type_id>/<str:object_id>/",
    name="components_save_layout_object"
)
@require_POST
def save_layout_object(
    request: HttpRequest,
    content_type_id: int,
    object_id: str,
) -> HttpResponse:
    """Endpoint to save a layout object"""
    content_type: ContentType = get_object_or_404(ContentType, id=content_type_id)
    model_cls = content_type.model_class()
    if model_cls is None:
        return HttpResponse("Invalid content type", status=400)

    func = CALLABLES.get(model_cls)
    if not func:
        raise Http404()

    obj = get_object_or_404(model_cls, id=object_id)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    result = func(request, obj, payload)
    if isinstance(result, HttpResponse):
        return result
    return JsonResponse(result)





