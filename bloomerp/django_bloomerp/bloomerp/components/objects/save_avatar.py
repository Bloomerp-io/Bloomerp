from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bloomerp.models import ApplicationField
from bloomerp.router import router
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.models import get_object_from_content_type


def _can_change_avatar(request: HttpRequest, object, content_type_id: int) -> bool:
    try:
        object._meta.get_field("avatar")
    except FieldDoesNotExist:
        return False

    avatar_field = ApplicationField.objects.filter(
        content_type_id=content_type_id,
        field="avatar",
    ).first()
    if not avatar_field:
        return False

    permission_str = create_permission_str(object, "change")
    permission_manager = UserPermissionManager(request.user)
    return (
        permission_manager.has_access_to_object(object, permission_str)
        and permission_manager.has_field_permission(avatar_field, permission_str)
    )


def _render_avatar(
    request: HttpRequest,
    object,
    content_type_id: int,
    status: int = 200,
    avatar_error: str | None = None,
) -> HttpResponse:
    return render(
        request,
        "components/objects/avatar_upload.html",
        {
            "object": object,
            "content_type_id": content_type_id,
            "can_change_avatar": _can_change_avatar(request, object, content_type_id),
            "avatar_error": avatar_error,
        },
        status=status,
    )


@router.register(
    path="components/objects/save_avatar/<int:content_type_id>/<str:object_id>/",
    name="components_save_avatar",
)
def save_avatar(request: HttpRequest, content_type_id: int, object_id: str):
    """Component to save a particular avatar

    Args:
        request (HttpRequest): _description_
        content_type_id (int): _description_
        object_id (str): _description_
    """
    object = get_object_from_content_type(content_type_id, object_id)
    if not object:
        return HttpResponse(status=404)

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    if not _can_change_avatar(request, object, content_type_id):
        return HttpResponse("Permission denied", status=403)

    if "avatar" not in request.FILES:
        return _render_avatar(
            request,
            object,
            content_type_id,
            status=400,
            avatar_error="Choose an image to upload.",
        )

    AvatarForm = forms.modelform_factory(object._meta.model, fields=["avatar"])
    form = AvatarForm(request.POST, request.FILES, instance=object)
    if not form.is_valid():
        error = form.errors.get("avatar")
        message = error[0] if error else "Could not save this avatar."
        return _render_avatar(
            request,
            object,
            content_type_id,
            status=400,
            avatar_error=message,
        )

    form.save()
    return _render_avatar(request, object, content_type_id)
