from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.models import File, FileFolder
from bloomerp.router import router
from bloomerp.services.file_permission_services import user_can_mutate_file
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message


class RenameFileForm(forms.Form):
    name = forms.CharField(max_length=100, label=_("Name"))


@router.register(
    path="components/files/<uuid:file_id>/rename/",
    name="components_files_rename",
)
@login_required
def rename_file(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render and process the modal form for renaming a file."""
    file = get_object_or_404(File, pk=file_id)
    if not user_can_mutate_file(request, file, ("change", "add")):
        return HttpResponse(status=403)

    if request.method == "POST":
        form = RenameFileForm(request.POST)
        if form.is_valid():
            file.name = form.cleaned_data["name"]
            file.updated_by = request.user
            file.save(update_fields=["name", "updated_by"])
            return render_page_refresh_with_message(
                request,
                message=_("File renamed successfully."),
                type="success",
            )
    elif request.method == "GET":
        form = RenameFileForm(initial={"name": file.name})
    else:
        return HttpResponse("Method not allowed", status=405)

    return render_blank_form(
        request,
        form=form,
        url=reverse("components_files_rename", kwargs={"file_id": file.pk}),
        submit_label=_("Rename"),
        button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
    )


@router.register(
    path="components/files/folders/rename/",
    name="components_files_rename_folder",
)
@login_required
def rename_folder(request: HttpRequest) -> HttpResponse:
    """Rename a folder from the file-browser folder controls."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    folder = get_object_or_404(FileFolder, id=request.POST.get("folder_id"))
    if not request.user.has_perm("bloomerp.change_filefolder"):
        return HttpResponse(status=403)

    name = (request.POST.get("name") or "").strip()
    if not name:
        return HttpResponse("Name is required", status=400)

    folder.name = name
    folder.updated_by = request.user
    folder.save(update_fields=["name", "updated_by"])
    return HttpResponse(status=204)
