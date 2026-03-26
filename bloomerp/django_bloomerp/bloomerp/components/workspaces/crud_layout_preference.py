import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from bloomerp.models import UserCreateViewPreference
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.sectioned_layout_services import normalize_layout_payload


def _get_layout_kind(payload: dict) -> str | None:
    """Read the CRUD layout kind from the request payload."""
    layout_kind = payload.get("layout_kind")
    if layout_kind in {"detail", "create"}:
        return layout_kind
    return None


def _get_preference_model(*, layout_kind: str):
    """Return the preference model for a CRUD layout kind."""
    return UserCreateViewPreference if layout_kind == "create" else UserDetailViewPreference


def _get_valid_field_ids(request: HttpRequest, *, content_type: ContentType, layout_kind: str) -> set[int]:
    """Return the field ids a user is allowed to persist in a CRUD layout."""
    if layout_kind == "create":
        return {
            field.pk
            for field in get_addable_fields(content_type=content_type, user=request.user)
        }
    return set(content_type.applicationfield_set.values_list("id", flat=True))


@router.register(
    path="components/workspaces/crud_layout_preference/",
    name="components_workspaces_crud_layout_preference",
)
def crud_layout_preference(request: HttpRequest) -> HttpResponse:
    """Persist a detail or create CRUD layout preference for the current user."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    content_type_id = payload.get("content_type_id")
    layout_kind = _get_layout_kind(payload)
    if not content_type_id:
        return HttpResponse("Missing content_type_id", status=400)
    if layout_kind is None:
        return HttpResponse("Missing or invalid layout_kind", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    permission_prefix = "add" if layout_kind == "create" else "view"
    if not request.user.has_perm(f"{model._meta.app_label}.{permission_prefix}_{model._meta.model_name}"):
        return HttpResponse("Permission denied", status=403)

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = _get_valid_field_ids(request, content_type=content_type, layout_kind=layout_kind)
    submitted_ids = {
        int(item.id)
        for row in layout.rows
        for item in row.items
        if str(item.id).isdigit()
    }
    if not submitted_ids.issubset(valid_ids):
        return HttpResponse("Unknown field id in layout", status=400)

    preference_model = _get_preference_model(layout_kind=layout_kind)
    preference = preference_model.get_or_create_for_user(request.user, content_type)
    preference.field_layout = layout.model_dump()
    preference.save(update_fields=["field_layout"])

    return JsonResponse({"status": "ok", "layout": layout.model_dump()})
