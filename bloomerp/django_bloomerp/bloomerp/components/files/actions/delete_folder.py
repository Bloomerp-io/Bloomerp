from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from bloomerp.models import FileFolder
from bloomerp.router import router
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.files.access import FileAccessManager
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message
from bloomerp.models.files.file_folder import user_can_delete_folder
from bloomerp.services.file_services import get_folder_descendants


@router.register(
    path="components/files/folders/<int:folder_id>/delete/",
    name="components_files_delete_folder",
)
@login_required
def delete_folder(request: HttpRequest, folder_id: int) -> HttpResponse:
    """Render and process the canonical delete-folder modal."""
    folder = get_object_or_404(FileFolder, id=folder_id)
    _descendant_folders, descendant_files = get_folder_descendants(folder)
    can_delete_files = all(
        FileAccessManager(request.user).has_access_to_file(
            file, (BloomerpPermission.DELETE,)
        )
        for file in descendant_files
    )
    if not (can_delete_files and user_can_delete_folder(request, folder)):
        return HttpResponse(status=403)

    if request.method == "GET":
        return render_blank_form(
            request,
            form=None,
            url=reverse(
                "components_files_delete_folder",
                kwargs={"folder_id": folder.pk},
            ),
            submit_label=_("Delete"),
            button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
            text=format_html(
                'Are you sure you want to delete <strong>"{}"</strong>? '
                "This also deletes its nested folders and files.",
                folder.name,
            ),
        )

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    folder_name = folder.name
    folder.delete()
    return render_page_refresh_with_message(
        request,
        message=_("Folder deleted successfully: %(name)s") % {"name": folder_name},
        type="success",
    )
