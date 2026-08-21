from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from bloomerp.components.files import (
    _coerce_query_value,
    _get_file_for_mutation,
    _get_target_folder,
    _user_can_view_folder,
)
from bloomerp.models import File, FileFolder
from bloomerp.router import router
from bloomerp.services.file_permission_services import user_can_mutate_file
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message


def _folder_accepts_file(folder: FileFolder | None, file: File) -> bool:
    if folder is None:
        return True
    return (
        folder.content_type_id == file.content_type_id
        and (folder.object_id or None) == (file.object_id or None)
    )


def _available_folders(
    request: HttpRequest,
    file: File,
) -> QuerySet[FileFolder]:
    folders = FileFolder.objects.filter(
        content_type_id=file.content_type_id,
        object_id=file.object_id,
    )
    visible_ids = [folder.pk for folder in folders if _user_can_view_folder(request, folder)]
    return FileFolder.objects.filter(pk__in=visible_ids).order_by("name")


class MoveFileForm(forms.Form):
    target_folder = forms.ModelChoiceField(
        queryset=FileFolder.objects.none(),
        required=False,
        empty_label=_("Root"),
        label=_("Destination folder"),
    )

    def __init__(self, *args, folders: QuerySet[FileFolder], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["target_folder"].queryset = folders


@router.register(
    path="components/files/<uuid:file_id>/move/",
    name="components_files_move",
)
@login_required
def move_file(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render and process the modal form for moving a file."""
    file = get_object_or_404(File, pk=file_id)
    if not user_can_mutate_file(request, file, ("change", "add")):
        return HttpResponse(status=403)

    folders = _available_folders(request, file)
    if request.method == "POST":
        form = MoveFileForm(request.POST, folders=folders)
        if form.is_valid():
            file.folder = form.cleaned_data["target_folder"]
            file.updated_by = request.user
            file.save(update_fields=["folder", "updated_by"])
            return render_page_refresh_with_message(
                request,
                message=_("File moved successfully."),
                type="success",
            )
    elif request.method == "GET":
        form = MoveFileForm(initial={"target_folder": file.folder_id}, folders=folders)
    else:
        return HttpResponse("Method not allowed", status=405)

    return render_blank_form(
        request,
        form=form,
        url=reverse("components_files_move", kwargs={"file_id": file.pk}),
        submit_label=_("Move"),
        button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
    )


@router.register(
    path="components/files/items/move/",
    name="components_files_move_browser_item",
)
@login_required
def move_file_browser_item(request: HttpRequest) -> HttpResponse:
    """Move a dragged file or folder within the file browser."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    item_type = request.POST.get("item_type")
    target_folder = _get_target_folder(
        _coerce_query_value(request.POST.get("target_folder_id"))
    )

    if item_type == "file":
        try:
            file = _get_file_for_mutation(request)
        except PermissionError:
            return HttpResponse(status=403)
        if not _folder_accepts_file(target_folder, file):
            return HttpResponse(
                "File cannot be moved into a folder with a different scope",
                status=400,
            )
        file.folder = target_folder
        file.updated_by = request.user
        file.save(update_fields=["folder", "updated_by"])
        return HttpResponse(status=204)

    if item_type == "folder":
        folder = get_object_or_404(FileFolder, id=request.POST.get("folder_id"))
        if not request.user.has_perm("bloomerp.change_filefolder"):
            return HttpResponse(status=403)

        if target_folder and target_folder.id == folder.id:
            return HttpResponse("Cannot move a folder into itself", status=400)

        ancestor = target_folder
        while ancestor is not None:
            if ancestor.id == folder.id:
                return HttpResponse(
                    "Cannot move a folder into its own descendant",
                    status=400,
                )
            ancestor = ancestor.parent

        if target_folder:
            folder.content_type = target_folder.content_type
            folder.object_id = target_folder.object_id

        folder.parent = target_folder
        folder.updated_by = request.user
        try:
            folder.save()
        except ValidationError as exc:
            return HttpResponse(exc.messages[0], status=400)
        return HttpResponse(status=204)

    return HttpResponse("Unsupported item type", status=400)
