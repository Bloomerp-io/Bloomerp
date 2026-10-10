from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message
from bloomerp.components.files.actions.rename_form import RenameFileForm
from bloomerp.models import FileFolder
from bloomerp.models.files.file_folder import user_can_change_folder


@router.register(
    path="components/files/folders/<int:folder_id>/rename/",
    name="components_files_rename_folder",
)
@login_required
def rename_folder(request: HttpRequest, folder_id: int) -> HttpResponse:
    """Render and process the canonical rename-folder modal."""
    folder = get_object_or_404(FileFolder, id=folder_id)
    if not user_can_change_folder(request, folder):
        return HttpResponse(status=403)

    if request.method == "POST":
        form = RenameFileForm(request.POST)
        if form.is_valid():
            folder.name = form.cleaned_data["name"]
            folder.updated_by = request.user
            folder.save(update_fields=["name", "updated_by"])
            return render_page_refresh_with_message(
                request,
                message=_("Folder renamed successfully."),
                type="success",
            )
    elif request.method == "GET":
        form = RenameFileForm(initial={"name": folder.name})
    else:
        return HttpResponse("Method not allowed", status=405)

    return render_blank_form(
        request,
        form=form,
        url=reverse(
            "components_files_rename_folder",
            kwargs={"folder_id": folder.pk},
        ),
        submit_label=_("Rename"),
        button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
    )
