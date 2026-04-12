import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from bloomerp.models import UserCreateViewPreference
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import create_permission_str
from bloomerp.services.sectioned_layout_services import get_available_layout_fields, normalize_layout_payload


def _get_legacy_layout_kind(payload: dict) -> str | None:
    layout_kind = payload.get("layout_kind")
    if layout_kind in {"detail", "create"}:
        return layout_kind
    return None


def _get_preference_model(*, scope: str):
    return UserCreateViewPreference if scope == "create" else UserDetailViewPreference


def _get_valid_field_ids(request: HttpRequest, *, content_type: ContentType, scope: str) -> set[int]:
    if scope == "create":
        return {
            field.pk
            for field in get_addable_fields(content_type=content_type, user=request.user)
        }
    return {
        int(item["id"])
        for item in get_available_layout_fields(
            content_type=content_type,
            user=request.user,
            layout_kind="detail",
        )
    }


def _save_layout_preference(request: HttpRequest, *, scope: str | None = None) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    content_type_id = payload.get("content_type_id")
    scope = scope or _get_legacy_layout_kind(payload)
    if not content_type_id:
        return HttpResponse("Missing content_type_id", status=400)
    if scope is None:
        return HttpResponse("Missing or invalid layout scope", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    permission = create_permission_str(model, "add" if scope == "create" else "view")
    if not request.user.has_perm(f"{model._meta.app_label}.{permission}"):
        return HttpResponse("Permission denied", status=403)

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = _get_valid_field_ids(request, content_type=content_type, scope=scope)
    submitted_ids = {
        int(item.id)
        for row in layout.rows
        for item in row.items
        if str(item.id).isdigit()
    }
    if not submitted_ids.issubset(valid_ids):
        return HttpResponse("Unknown field id in layout", status=400)

    preference_model = _get_preference_model(scope=scope)
    preference = preference_model.get_or_create_for_user(request.user, content_type)
    preference.field_layout = layout.model_dump()
    preference.save(update_fields=["field_layout"])
    return JsonResponse({"status": "ok", "layout": layout.model_dump()})


@router.register(
    path="components/workspaces/crud_layout_preference/",
    name="components_workspaces_crud_layout_preference",
)
def crud_layout_preference(request: HttpRequest) -> HttpResponse:
    return _save_layout_preference(request)


@router.register(
    path="components/workspaces/create_layout_preference/",
    name="components_workspaces_create_layout_preference",
)
def create_layout_preference(request: HttpRequest) -> HttpResponse:
    return _save_layout_preference(request, scope="create")


@router.register(
    path="components/workspaces/detail_layout_preference/",
    name="components_workspaces_detail_layout_preference",
)
def detail_layout_preference(request: HttpRequest) -> HttpResponse:
    return _save_layout_preference(request, scope="detail")
