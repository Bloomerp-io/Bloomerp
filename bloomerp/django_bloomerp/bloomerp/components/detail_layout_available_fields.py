from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import get_available_detail_fields


@router.register(
    path="components/detail_layout_available_fields/",
    name="components_detail_layout_available_fields",
)
def detail_layout_available_fields(request: HttpRequest) -> HttpResponse:
    """
    Returns the available fields for detail layout fields.
    """
    content_type_id = request.GET.get("content_type_id")
    if not content_type_id:
        return HttpResponse("Missing content_type_id", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    if not request.user.has_perm(f"{model._meta.app_label}.view_{model._meta.model_name}"):
        return HttpResponse("Permission denied", status=403)
    
    return render(
        request,
        "components/layouts/available_items.html",
        {"items": get_available_detail_fields(content_type=content_type, user=request.user)},
    )
