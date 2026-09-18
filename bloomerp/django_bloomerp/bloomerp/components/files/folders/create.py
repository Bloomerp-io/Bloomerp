from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.models import FileFolder
from bloomerp.router import router
from bloomerp.services.file_permission_services import has_linked_file_permission
from bloomerp.services.file_services import (
    coerce_file_scope_value,
    ensure_folder_hierarchy_for_object,
    get_folder_linked_object,
    get_model_scope_folder,
    get_object_folder_scope_key,
    get_target_folder,
    resolve_file_scope,
)
from bloomerp.utils.requests import (
    render_blank_form,
    render_page_refresh_with_message,
)
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class FolderCreationScope:
    content_type: ContentType | None
    linked_object: object | None
    parent_folder: FileFolder | None


class CreateFolderForm(forms.Form):
    name = forms.CharField(max_length=255, label=_("Name"))


def _request_scope_value(request: HttpRequest, *keys: str) -> str | None:
    source = request.POST if request.method == "POST" else request.GET
    for key in keys:
        value = coerce_file_scope_value(source.get(key))
        if value is not None:
            return value

    if request.method == "GET":
        current_url = request.headers.get("HX-Current-URL")
        current_query = parse_qs(urlsplit(current_url).query) if current_url else {}
        for key in keys:
            values = current_query.get(key, [])
            value = coerce_file_scope_value(values[-1] if values else None)
            if value is not None:
                return value

    return None


def _resolve_folder_creation_scope(
    request: HttpRequest,
    *,
    create_object_folder: bool = False,
) -> FolderCreationScope:
    parent_folder = get_target_folder(
        _request_scope_value(request, "parent_folder_id", "folder_id", "folder")
    )
    if parent_folder is not None:
        return FolderCreationScope(
            content_type=parent_folder.content_type,
            linked_object=get_folder_linked_object(parent_folder),
            parent_folder=parent_folder,
        )

    content_type_id = _request_scope_value(
        request,
        "content_type_id",
        "content_type",
    )
    object_id = _request_scope_value(request, "object_id")
    if content_type_id and object_id:
        content_type, linked_object = resolve_file_scope(content_type_id, object_id)
    elif content_type_id:
        content_type = get_object_or_404(ContentType, pk=content_type_id)
        linked_object = None
    else:
        content_type = None
        linked_object = None

    if linked_object is not None:
        object_folder = FileFolder.objects.filter(
            kind=FileFolder.Kind.OBJECT,
            scope_key=get_object_folder_scope_key(content_type, linked_object.pk),
        ).first()
        if object_folder is None and create_object_folder:
            object_folder = ensure_folder_hierarchy_for_object(
                linked_object,
                created_by=request.user,
                updated_by=request.user,
            )
        parent_folder = object_folder
    elif content_type is not None:
        parent_folder = get_model_scope_folder(content_type)

    return FolderCreationScope(
        content_type=content_type,
        linked_object=linked_object,
        parent_folder=parent_folder,
    )


def can_create_folder(request: HttpRequest) -> bool:
    """Return whether the request user may create a folder in this browser scope."""
    if request.user.is_superuser:
        return True

    scope = _resolve_folder_creation_scope(request)
    if scope.linked_object is not None:
        return has_linked_file_permission(request, scope.linked_object, "add")
    return request.user.has_perm("bloomerp.add_filefolder")


def _render_create_folder_form(
    request: HttpRequest,
    form: CreateFolderForm,
    scope: FolderCreationScope,
) -> HttpResponse:
    hidden_args = {
        "folder_id": scope.parent_folder.pk if scope.parent_folder else "",
        "content_type_id": scope.content_type.pk if scope.content_type else "",
        "object_id": (
            str(scope.linked_object.pk) if scope.linked_object is not None else ""
        ),
    }
    return render_blank_form(
        request,
        form,
        reverse("components_create_folder"),
        hidden_args=hidden_args,
        submit_label=_("Create"),
        button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
    )


@router.register(
    path="components/files/create_folder",
    url_name="components_create_folder",
)
@login_required
def create_folder(request: HttpRequest) -> HttpResponse:
    """Render and process the canonical create-folder modal."""
    if request.method not in {"GET", "POST"}:
        return HttpResponse("Method not allowed", status=405)

    if not can_create_folder(request):
        return HttpResponse(status=403)

    scope = _resolve_folder_creation_scope(
        request,
        create_object_folder=request.method == "POST",
    )
    form = CreateFolderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        folder = FileFolder(
            name=form.cleaned_data["name"],
            parent=scope.parent_folder,
            content_type=scope.content_type,
            object_id=(
                str(scope.linked_object.pk)
                if scope.linked_object is not None
                else (
                    scope.parent_folder.object_id
                    if scope.parent_folder is not None
                    else None
                )
            ),
            created_by=request.user,
            updated_by=request.user,
        )
        try:
            folder.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return render_page_refresh_with_message(
                request,
                message=_("Folder created successfully: %(name)s")
                % {"name": folder.name},
                type="success",
            )

    return _render_create_folder_form(request, form, scope)
