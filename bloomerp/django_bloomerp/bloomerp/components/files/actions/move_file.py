from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib.auth.decorators import login_required
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.files.access import FileAccessManager
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message

if TYPE_CHECKING:
    from bloomerp.models.files.file_node import FileNode


def _available_folders(request: HttpRequest) -> QuerySet[FileNode]:
    """Return physical folder nodes the requester may modify."""
    from bloomerp.models.files.file_node import FileNode

    access = FileAccessManager(request.user)
    ids = [
        folder.pk
        for folder in FileNode.objects.filter(kind="FOLDER")
        if access.can_mutate_file_node(folder)
    ]
    return FileNode.objects.filter(pk__in=ids).order_by("name")


class MoveFileForm(forms.Form):
    """Select a visible destination folder or the root of the current scope."""

    target_folder = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label=_("Root"),
        label=_("Destination folder"),
    )

    def __init__(self, *args: Any, folders: QuerySet[FileNode], **kwargs: Any) -> None:
        """Restrict destination choices to the folders available to the requester."""
        super().__init__(*args, **kwargs)
        self.fields["target_folder"].queryset = folders


@router.register(
    path="components/files/<uuid:file_id>/move/",
    name="components_files_move",
)
@login_required
def move_file(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render and process the modal form for moving a file."""
    from bloomerp.models.files.file_node import FileNode

    file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
    if not FileAccessManager(request.user).can_mutate_file_node(
        file, BloomerpPermission.CHANGE
    ):
        return HttpResponse(status=403)

    folders = _available_folders(request)
    if request.method == "POST":
        form = MoveFileForm(request.POST, folders=folders)
        if form.is_valid():
            file.parent = form.cleaned_data["target_folder"]
            file.updated_by = request.user
            file.save(update_fields=["parent", "updated_by"])
            return render_page_refresh_with_message(
                request,
                message=_("File moved successfully."),
                type="success",
            )
    elif request.method == "GET":
        form = MoveFileForm(initial={"target_folder": file.parent_id}, folders=folders)
    else:
        return HttpResponse("Method not allowed", status=405)

    return render_blank_form(
        request,
        form=form,
        url=reverse("components_files_move", kwargs={"file_id": file.pk}),
        submit_label=_("Move"),
        button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
    )
