from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.models.application_field import ApplicationField
from bloomerp.router import router
from bloomerp.services.sectioned_layout_services import build_detail_value_context
from bloomerp.services.permission_services import UserPermissionManager


@router.register(
    path="components/detail_layout_render_field/",
    name="components_detail_layout_render_field",
)
def detail_layout_render_field(request: HttpRequest) -> HttpResponse:
    """
    Renders a detail field.
    """
    content_type_id = request.GET.get("content_type_id")
    object_id = request.GET.get("object_id")
    field_id = request.GET.get("field_id")
    if not content_type_id or not object_id or not field_id:
        return HttpResponse("Missing render parameters", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    permission_manager = UserPermissionManager(request.user)

    view_permission = f"view_{model._meta.model_name}"
    allowed_queryset = permission_manager.get_queryset(model, view_permission)
    obj = get_object_or_404(allowed_queryset, pk=object_id)

    application_field = get_object_or_404(ApplicationField, pk=field_id, content_type=content_type)

    context = build_detail_value_context(
        obj=obj,
        application_field=application_field,
        can_edit=permission_manager.has_field_permission(application_field, f"change_{model._meta.model_name}"),
    )
    context["colspan"] = request.GET.get("colspan", 1)

    return render(request, "inclusion_tags/detail_view_value.html", context)
