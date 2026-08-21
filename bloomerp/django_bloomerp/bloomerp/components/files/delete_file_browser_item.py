from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from bloomerp.components.files import _get_folder_descendants, _user_can_mutate_file
from bloomerp.models import File, FileFolder
from bloomerp.router import router
from bloomerp.services.file_permission_services import user_can_mutate_file
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message


@router.register(
    path="components/files/<uuid:file_id>/delete/",
    name="components_files_delete",
)
@login_required
def delete_file(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render and process the modal confirmation for deleting a file."""
    file = get_object_or_404(File, pk=file_id)
    if not user_can_mutate_file(request, file, ("delete",)):
        return HttpResponse(status=403)

    if request.method == "GET":
        return render_blank_form(
            request,
            form=None,
            url=reverse("components_files_delete", kwargs={"file_id": file.pk}),
            submit_label=_("Delete"),
            button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
            text=format_html(
                'Are you sure you want to delete <strong>"{}"</strong>? '
                "This action cannot be undone.",
                file.name,
            ),
        )

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    file_name = file.name
    file.delete()
    return render_page_refresh_with_message(
        request,
        message=_("File deleted successfully: %(name)s") % {"name": file_name},
        type="success",
    )


@router.register(
    path="components/files/folders/delete/",
    name="components_files_delete_folder",
)
@login_required
def delete_folder(request: HttpRequest) -> HttpResponse:
    """Delete a folder from the file-browser folder controls."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    folder = get_object_or_404(FileFolder, id=request.POST.get("folder_id"))
    _descendant_folders, descendant_files = _get_folder_descendants(folder)
    can_delete_files = all(
        _user_can_mutate_file(request, file, ("delete",))
        for file in descendant_files
    )
    if not (can_delete_files and request.user.has_perm("bloomerp.delete_filefolder")):
        return HttpResponse(status=403)

    folder.delete()
    return HttpResponse(status=204)
