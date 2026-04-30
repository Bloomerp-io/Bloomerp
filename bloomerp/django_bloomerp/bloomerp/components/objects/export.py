from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import reverse

from bloomerp.forms.bulk_upload_form import BloomerpBulkForm
from bloomerp.models.application_field import ApplicationField
from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404

from django.db.models import Model, QuerySet

from bloomerp.services.export_services import ExportService, wrap_export_bytes
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str


def _validation_error_to_text(exc: ValidationError) -> str:
    if hasattr(exc, "messages") and exc.messages:
        return " ".join(str(message) for message in exc.messages)
    return str(exc)


def _get(request: HttpRequest, content_type: ContentType, form: BloomerpBulkForm):
    querystring = request.GET.urlencode()
    post_url = reverse("components_export_objects", kwargs={"content_type_id": content_type.id})
    if querystring:
        post_url = f"{post_url}?{querystring}"

    return render(
        request,
        "components/bulk_actions/bulk_template_form.html",
        {
            "form": form,
            "content_type_id": content_type.id,
            "post_url": post_url,
        },
    )


def _post(
    request: HttpRequest,
    content_type: ContentType,
    form: BloomerpBulkForm,
    application_fields: QuerySet[ApplicationField],
    permission_str: str,
):
    if not form.is_valid():
        return _get(request, content_type, form)

    selected_field_names = form.get_selected_fields()

    # This ensures that only the accessible fields are included in the export,
    # even if the user manipulates the form data.
    fields = application_fields.filter(field__in=selected_field_names)
    fields_by_name = {
        application_field.field: application_field
        for application_field in fields
    }
    ordered_fields = [
        fields_by_name[field_name]
        for field_name in selected_field_names
        if field_name in fields_by_name
    ]

    try:
        service = ExportService(
            model=content_type.model_class(),
            user=request.user,
            permission_str=permission_str,
        )
        export_bytes, export_content_type, extension = service.create_export_bytes(
            application_fields=ordered_fields,
            file_type=form.cleaned_data["file_type"],
            query_params=request.GET,
        )
    except ValidationError as exc:
        form.add_error(None, _validation_error_to_text(exc))
        return _get(request, content_type, form)

    response = FileResponse(wrap_export_bytes(export_bytes), content_type=export_content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="{service.create_export_filename(extension)}"'
    )
    return response

def _get_permission_string(model: type[Model]) -> str:
    """Retrieves the permission string based on what the user can see

    Args:
        model (type[Model]): _description_

    Returns:
        str: _description_
    """
    if ("export" not in model._meta.permissions) and ("export" not in model._meta.default_permissions):
        return create_permission_str(model, "view")
    
    return create_permission_str(model, "export")

@router.register(
    path="components/objects/export/<int:content_type_id>/",
    name="components_export_objects",
)
def export_objects(request: HttpRequest, content_type_id: int):
    """Component that exports objects to the user based on the content type.

    Args:
        request (HttpRequest): http request object
        content_type_id (int): the content type ID of the objects to export
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)

    # Check permissions
    permission_str = _get_permission_string(content_type.model_class())
    permission_manager = UserPermissionManager(request.user)
    if not permission_manager.has_global_permission(
        content_type,
        permission_str,
    ):
        return HttpResponse("You do not have permission to export these objects.")
    
    # Get the application fields
    application_fields = permission_manager.get_accessible_fields(
        content_type,
        permission_str,
    )
    
    # Get the form
    form = BloomerpBulkForm(
        data=request.POST if request.method == "POST" else None,
        content_type=content_type,
        application_fields=application_fields,
        skip_ineligible_fields=False,
        mode="export",
    )
    
    match request.method:
        case "POST":
            return _post(request, content_type, form, application_fields, permission_str)

        case "GET":
            return _get(request, content_type, form)

    return HttpResponseNotAllowed(["GET", "POST"])
