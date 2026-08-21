from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.detail_view_services import get_default_layout
from bloomerp.services.preference_services import PreferenceManager
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
    policy_manager = UserPolicyManager(request.user)

    access_denied_message = None
    if not policy_manager.has_access_to_object(obj, BloomerpPermission.VIEW):
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
    preference = PreferenceManager(request.user).get_or_create_selected(
        UserObjectLayoutPreference,
        scope={
            "content_type_id" : content_type.id
        }
    )
    layout = {
        "rows": resolve_detail_layout_rows(
            layout=preference.layout_obj,
            content_type=content_type,
            user=request.user,
        )
    }

    if not any(row.get("items") for row in layout["rows"]):
        preference.layout = get_default_layout(content_type=content_type, user=request.user).model_dump()
        preference.save(update_fields=["layout"])
        layout = {
            "rows": resolve_detail_layout_rows(
                layout=preference.layout_obj,
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
