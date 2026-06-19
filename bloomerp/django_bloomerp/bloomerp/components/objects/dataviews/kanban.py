from bloomerp.models import ApplicationField
from bloomerp.router import router
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str


from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404


@router.register(
    path="components/kanban_move_card/<int:content_type_id>/",
    name="components_kanban_move_card",
)
def kanban_move_card(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Updates a kanban card's grouping field value.

    Expects POST data:
        object_id: the model instance ID to update
        group_by_field_id: ApplicationField ID used for kanban grouping
        group_value: the new value for the grouping field (or "__none__")
    """
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    object_id = request.POST.get("object_id")
    group_by_field_id = request.POST.get("group_by_field_id")
    group_value = request.POST.get("group_value")

    if not object_id or not group_by_field_id:
        return HttpResponse("Missing required fields", status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return HttpResponse("Invalid content type", status=400)

    application_field = get_object_or_404(
        ApplicationField,
        id=group_by_field_id,
        content_type=content_type
    )

    obj = get_object_or_404(model, id=object_id)
    permission_str = create_permission_str(model, "change")

    permission_manager = UserPermissionManager(request.user)
    if not permission_manager.has_access_to_object(obj, permission_str):
        return HttpResponse("Permission denied", status=403)
    if not permission_manager.has_field_permission(application_field, permission_str):
        return HttpResponse("Permission denied", status=403)

    model_field = model._meta.get_field(application_field.field)

    normalized_value = None if group_value in (None, "", "__none__") else group_value
    if normalized_value is None:
        if not model_field.null and not model_field.blank:
            return HttpResponse("Field does not allow empty values", status=400)
        setattr(obj, application_field.field, None)
    else:
        try:
            if model_field.many_to_one or model_field.one_to_one:
                related_model = model_field.remote_field.model
                related_obj = related_model.objects.get(pk=normalized_value)
                setattr(obj, application_field.field, related_obj)
            else:
                typed_value = model_field.to_python(normalized_value)
                setattr(obj, application_field.field, typed_value)
        except Exception as exc:
            return HttpResponse(f"Invalid value: {exc}", status=400)

    obj.save(update_fields=[application_field.field])

    return JsonResponse({"status": "ok"})