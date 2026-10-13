from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from bloomerp.files.access import FileAccessManager
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message


@router.register(
    path="components/files/<uuid:file_id>/delete/",
    name="components_files_delete",
)
@login_required
def delete_file(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render and process the modal confirmation for deleting a file."""
    from bloomerp.models.files.file_node import FileNode

    file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
    if not FileAccessManager(request.user).can_mutate_file_node(
        file, BloomerpPermission.DELETE
    ):
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
    from django.db.models.deletion import ProtectedError, RestrictedError

    try:
        file.delete()
    except (ProtectedError, RestrictedError):
        return HttpResponse(
            "This file is still referenced. Remove its references before deleting it.",
            status=409,
        )
    return render_page_refresh_with_message(
        request,
        message=_("File deleted successfully: %(name)s") % {"name": file_name},
        type="success",
    )
