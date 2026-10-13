from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.components.files.actions.rename_form import RenameFileForm
from bloomerp.files.access import FileAccessManager
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message


@router.register(
    path="components/files/<uuid:file_id>/rename/",
    name="components_files_rename",
)
@login_required
def rename_file(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render and process the modal form for renaming a file."""
    from bloomerp.models.files.file_node import FileNode

    file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
    if not FileAccessManager(request.user).can_mutate_file_node(
        file, BloomerpPermission.CHANGE
    ):
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
