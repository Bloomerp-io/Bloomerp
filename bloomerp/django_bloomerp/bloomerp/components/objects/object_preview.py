from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string

from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.detail_view_services import get_default_layout
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import resolve_detail_layout_rows


@router.register(
    path="components/object-preview/<int:content_type_id>/<str:object_id>/",
    name="components_object_preview",
)
def object_preview(request: HttpRequest, content_type_id: int, object_id: str) -> HttpResponse:
    """
    Component that gives a preview of a particular object. Is similar to the actual detail overview
    view.
    """
    model = get_object_or_404(ContentType, pk=content_type_id).model_class()
    if model is None:
        return HttpResponse(status=404)

    obj = get_object_or_404(model, pk=object_id)
    permission_str = create_permission_str(model, "view")
    permission_manager = UserPermissionManager(request.user)

    access_denied_message = None
    if not request.user.has_perm(f"{model._meta.app_label}.{permission_str}"):
        access_denied_message = "You do not have permission to preview this object."
    elif not permission_manager.has_access_to_object(obj, permission_str):
        access_denied_message = "You do not have direct access to this object."

    if access_denied_message:
        return render(
            request,
            "components/objects/object_preview.html",
            {
                "object": obj,
                "object_verbose_name": obj._meta.verbose_name,
                "access_denied_message": access_denied_message,
            },
        )

    content_type = ContentType.objects.get_for_model(model)
    preference = UserDetailViewPreference.get_or_create_for_user(request.user, content_type)
    layout = {
        "rows": resolve_detail_layout_rows(
            layout=preference.field_layout_obj,
            content_type=content_type,
            user=request.user,
        )
    }

    if not any(row.get("items") for row in layout["rows"]):
        preference.field_layout = get_default_layout(content_type=content_type, user=request.user).model_dump()
        preference.save(update_fields=["field_layout"])
        layout = {
            "rows": resolve_detail_layout_rows(
                layout=preference.field_layout_obj,
                content_type=content_type,
                user=request.user,
            )
        }

    context = {
        "object": obj,
        "layout": layout,
        "object_verbose_name": obj._meta.verbose_name,
    }

    try:
        return HttpResponse(
            render_to_string(
                "components/objects/object_preview.html",
                context,
                request=request,
            )
        )
    except Exception:
        context["preview_error_message"] = "Preview is not available for this object type."
        context.pop("layout", None)
        return HttpResponse(
            render_to_string(
                "components/objects/object_preview.html",
                context,
                request=request,
            )
        )
