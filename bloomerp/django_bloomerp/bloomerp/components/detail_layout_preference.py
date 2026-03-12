import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import normalize_layout_payload

# TODO: This should become an api endpoint as it returns json. To do that, just move it to an api endpoint instead

@router.register(
    path="components/detail_layout_preference/",
    name="components_detail_layout_preference",
)
def detail_layout_preference(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    content_type_id = payload.get("content_type_id")
    if not content_type_id:
        return HttpResponse("Missing content_type_id", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    if not request.user.has_perm(f"{model._meta.app_label}.view_{model._meta.model_name}"):
        return HttpResponse("Permission denied", status=403)

    layout = normalize_layout_payload(payload.get("layout"))
    valid_ids = set(content_type.applicationfield_set.values_list("id", flat=True))
    requested_ids = {
        int(item.id)
        for row in layout.rows
        for item in row.items
        if str(item.id).isdigit()
    }
    if not requested_ids.issubset(valid_ids):
        return HttpResponse("Unknown field id in layout", status=400)

    preference = UserDetailViewPreference.get_or_create_for_user(request.user, content_type)
    preference.field_layout = layout.model_dump()
    preference.save(update_fields=["field_layout"])

    return JsonResponse({"status": "ok", "layout": layout.model_dump()})
