from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import reverse

from bloomerp.router import router
from bloomerp.services.bulk_services import BulkCrudService, wrap_template_bytes


def _get_service(request: HttpRequest, content_type_id: int) -> BulkCrudService:
    return BulkCrudService.from_content_type_id(content_type_id=content_type_id, user=request.user)


def _validation_error_to_text(exc: ValidationError) -> str:
    if hasattr(exc, "messages") and exc.messages:
        return " ".join(str(message) for message in exc.messages)
    return str(exc)


@router.register(
    path="components/bulk-upload/<int:content_type_id>/form/",
    url_name="components_bulk_upload_form",
)
@login_required
def bulk_upload_form(request: HttpRequest, content_type_id: int):
    """
    Return and process the download-template form used by the bulk upload wizard.
    """
    try:
        service = _get_service(request, content_type_id)
    except Exception:
        return HttpResponse("Invalid content type", status=400)

    if not service.can_access_page():
        return HttpResponse("Permission denied", status=403)

    if request.method == "GET":
        form = service.build_template_form()
        return render(
            request,
            "components/bulk_actions/download_bulk_upload_template_form.html",
            {
                "form": form,
                "content_type_id": content_type_id,
                "post_url": reverse("components_bulk_upload_form", kwargs={"content_type_id": content_type_id}),
            },
        )

    if request.method == "POST":
        form = service.build_template_form(data=request.POST)
        if not form.is_valid():
            return render(
                request,
                "components/bulk_actions/download_bulk_upload_template_form.html",
                {
                    "form": form,
                    "content_type_id": content_type_id,
                    "post_url": reverse("components_bulk_upload_form", kwargs={"content_type_id": content_type_id}),
                },
                status=400,
            )

        try:
            template_bytes, content_type, extension = service.create_template_bytes(
                fields=form.get_selected_fields(),
                file_type=form.cleaned_data["file_type"],
            )
        except ValidationError as exc:
            form.add_error(None, _validation_error_to_text(exc))
            return render(
                request,
                "components/bulk_actions/download_bulk_upload_template_form.html",
                {
                    "form": form,
                    "content_type_id": content_type_id,
                    "post_url": reverse("components_bulk_upload_form", kwargs={"content_type_id": content_type_id}),
                },
                status=400,
            )

        response = FileResponse(wrap_template_bytes(template_bytes), content_type=content_type)
        response["Content-Disposition"] = (
            f'attachment; filename="{service.create_template_filename(extension)}"'
        )
        return response

    return HttpResponseNotAllowed(["GET", "POST"])
