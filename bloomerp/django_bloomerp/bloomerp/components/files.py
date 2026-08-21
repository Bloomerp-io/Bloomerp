from urllib.parse import parse_qs
from dataclasses import dataclass
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from bloomerp.components.objects.dataviews.dataview import dataview
from bloomerp.models import ApplicationField, File, FileFolder
from bloomerp.router import router
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object
from bloomerp.permissions.manager import UserPermissionManager
from bloomerp.permissions.manager import create_permission_str


__path__ = [str(Path(__file__).with_name("files"))]

FILE_BROWSER_RESERVED_QUERY_KEYS = {
    "q",
    "page",
    "_render_id",
    "module_id",
    "folder",
    "folder_id",
    "content_type",
    "content_type_id",
    "object_id",
    "hide_ancestor_folders",
    "view_type",
}


@dataclass
class FilePermissionContext:
    file: File
    linked_object: object | None
    files_field: ApplicationField | None


@dataclass
class FileBrowserScope:
    content_type: ContentType | None
    linked_object: object | None
    current_folder: FileFolder | None


def _get_file_content_type() -> ContentType:
    return ContentType.objects.get_for_model(File)


def _resolve_linked_object(
    *,
    content_type: ContentType | None,
    object_id: str | None,
):
    if content_type is None or object_id in {None, "", "None"}:
        return None

    model = content_type.model_class()
    if model is None:
        return None

    return model._base_manager.filter(pk=object_id).first()


def _get_folder_linked_object(folder: FileFolder):
    return _resolve_linked_object(
        content_type=folder.content_type,
        object_id=folder.object_id,
    )


def _get_file_linked_object(file: File):
    return _resolve_linked_object(
        content_type=file.content_type,
        object_id=file.object_id,
    )


def _coerce_query_value(value: str | None) -> str | None:
    if value in {"", "None", None}:
        return None
    return value


def _get_request_value(request: HttpRequest, *keys: str) -> str | None:
    for key in keys:
        value = _coerce_query_value(request.GET.get(key))
        if value is not None:
            return value
    return None


def _hydrate_legacy_querystring(request: HttpRequest, legacy_query: str | None = None) -> None:
    candidate = legacy_query
    if candidate is None:
        candidate = request.path.rsplit("/", 1)[-1]

    if not candidate or candidate[0] not in {"?", "&"}:
        return

    query_dict = QueryDict("", mutable=True)
    for key, values in parse_qs(candidate.lstrip("?&"), keep_blank_values=True).items():
        for value in values:
            query_dict.appendlist(key, value)
    request.GET = query_dict


def _folder_path(folder: FileFolder) -> str:
    return " / ".join([_get_folder_display_name(parent) for parent in folder.parents] + [_get_folder_display_name(folder)])


def _get_folder_display_name(folder: FileFolder) -> str:
    if not folder.protected:
        return folder.name

    linked_object = _get_folder_linked_object(folder)
    if linked_object is not None:
        return str(linked_object)

    if folder.content_type_id and not folder.object_id:
        model = folder.content_type.model_class() if folder.content_type else None
        if model is not None:
            return str(model._meta.verbose_name_plural)

    if (
        folder.parent_id is None
        and folder.content_type_id is None
        and not folder.object_id
    ):
        from bloomerp.modules.definition import module_registry

        module = next(
            (
                item
                for item in module_registry.get_root_modules()
                if item.name == folder.name
            ),
            None,
        )
        if module is not None:
            return module.localized_name

    return folder.name


def _get_object_scope(content_type_id: str | None, object_id: str | None):
    if not content_type_id or not object_id:
        return None, None

    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    if model is None:
        return content_type, None

    return content_type, get_object_or_404(model, pk=object_id)


def _get_linked_object_files_field(linked_object) -> ApplicationField | None:
    if linked_object is None:
        return None

    return ApplicationField.get_by_field(linked_object.__class__, "files")


def _check_linked_file_permission(
    *,
    request: HttpRequest,
    linked_object,
    files_field: ApplicationField | None,
    operation: str,
) -> bool:
    if linked_object is None:
        return False

    permission_manager = UserPermissionManager(request.user)
    if not permission_manager.has_access_to_object(
        linked_object,
        create_permission_str(linked_object, "view"),
    ):
        return False

    if files_field is None:
        return False

    return permission_manager.has_field_permission(
        files_field,
        create_permission_str(linked_object, operation),
    )


def _resolve_file_permission_context(file: File) -> FilePermissionContext:
    linked_object = _get_file_linked_object(file)
    files_field = _get_linked_object_files_field(linked_object) if linked_object else None
    return FilePermissionContext(file=file, linked_object=linked_object, files_field=files_field)


def _user_can_view_file(request: HttpRequest, file: File) -> bool:
    if request.user.is_superuser:
        return True

    context = _resolve_file_permission_context(file)
    if context.linked_object is not None:
        return _check_linked_file_permission(
            request=request,
            linked_object=context.linked_object,
            files_field=context.files_field,
            operation="view",
        )

    permission_manager = UserPermissionManager(request.user)
    return permission_manager.has_global_permission(File, create_permission_str(File, "view"))


def _user_can_mutate_file(request: HttpRequest, file: File, operations: tuple[str, ...]) -> bool:
    if request.user.is_superuser:
        return True

    context = _resolve_file_permission_context(file)
    if context.linked_object is not None:
        return any(
            _check_linked_file_permission(
                request=request,
                linked_object=context.linked_object,
                files_field=context.files_field,
                operation=operation,
            )
            for operation in operations
        )

    permission_manager = UserPermissionManager(request.user)
    return any(
        permission_manager.has_global_permission(File, create_permission_str(File, operation))
        for operation in operations
    )


def _user_can_view_folder(request: HttpRequest, folder: FileFolder) -> bool:
    if request.user.is_superuser:
        return True

    if request.user.has_perm("bloomerp.view_file"):
        return True

    linked_object = _get_folder_linked_object(folder)
    if linked_object is not None:
        return _check_linked_file_permission(
            request=request,
            linked_object=linked_object,
            files_field=_get_linked_object_files_field(linked_object),
            operation="view",
        )

    for file in folder.files.all():
        if _user_can_view_file(request, file):
            return True

    child_folders = FileFolder.objects.filter(parent=folder).prefetch_related("files")
    return any(_user_can_view_folder(request, child_folder) for child_folder in child_folders)


def _build_visible_folders_queryset(
    *,
    request: HttpRequest,
    content_type_id: str | None,
    object_id: str | None,
    current_folder: FileFolder | None,
    query: str | None,
) -> QuerySet[FileFolder]:
    if query:
        if current_folder:
            folders = FileFolder.objects.filter(id__in=_get_descendant_folder_ids(current_folder))
        else:
            folders = FileFolder.objects.all()
    else:
        folders = (
            FileFolder.objects.filter(parent=current_folder)
            if current_folder
            else FileFolder.objects.filter(parent=None)
        )

    if not current_folder:
        if content_type_id:
            folders = folders.filter(content_type_id=content_type_id)
        else:
            folders = folders.filter(content_type__isnull=True)

        if object_id:
            folders = folders.filter(object_id=object_id)
        else:
            folders = folders.filter(object_id__isnull=True)

    if query:
        folders = folders.filter(name__icontains=query)

    visible_ids = [folder.id for folder in folders.distinct() if _user_can_view_folder(request, folder)]
    return FileFolder.objects.filter(id__in=visible_ids)


def _build_visible_files_queryset(
    *,
    request: HttpRequest,
    content_type_id: str | None,
    object_id: str | None,
    current_folder: FileFolder | None,
    query: str | None,
):
    permission_manager = UserPermissionManager(request.user)
    files = File.objects.select_related("content_type", "created_by", "updated_by")

    if query and current_folder:
        descendant_ids = _get_descendant_folder_ids(current_folder)
        files = files.filter(folder_id__in=[current_folder.id, *descendant_ids])
    elif current_folder:
        files = files.filter(folder=current_folder)
    elif query and not content_type_id and not object_id:
        files = files.all()
    else:
        files = files.filter(folder__isnull=True)

    if content_type_id and not current_folder:
        files = files.filter(content_type_id=content_type_id)

    if object_id and not current_folder:
        files = files.filter(object_id=object_id)

    if query:
        files = files.filter(name__icontains=query)

    base_visible_ids: list[str] = []
    for file in files.distinct():
        if not file.content_type_id:
            if permission_manager.has_global_permission(File, create_permission_str(File, "view")):
                base_visible_ids.append(str(file.pk))
            continue

        if _user_can_view_file(request, file):
            base_visible_ids.append(str(file.pk))

    queryset = File.objects.filter(pk__in=base_visible_ids).select_related(
        "content_type",
        "created_by",
        "updated_by",
    )

    return queryset.order_by("name")


def _get_model_scope_folder(content_type: ContentType | None) -> FileFolder | None:
    if content_type is None:
        return None

    return (
        FileFolder.objects.filter(
            content_type=content_type,
            object_id__isnull=True,
        )
        .order_by("id")
        .first()
    )


def _serialize_folder_item(
    folder: FileFolder,
    *,
    query: str | None = None,
    current_folder: FileFolder | None = None,
) -> dict:
    return {
        "id": str(folder.id),
        "name": _get_folder_display_name(folder),
        "kind_label": "Folder",
        "location_label": (
            "Search result"
            if query and not current_folder
            else (_get_folder_display_name(folder.parent) if folder.parent_id else "Root")
        ),
        "icon_class": "fa fa-folder text-amber-500",
        "open_folder_id": str(folder.id),
        "rename_allowed": not folder.protected,
        "delete_allowed": not folder.protected,
        "is_dropzone": True,
        "folder": folder,
    }


def _build_navigation_items(
    *,
    request: HttpRequest,
    scope: FileBrowserScope,
    query: str | None,
) -> list[dict]:
    if scope.current_folder:
        folders = _build_visible_folders_queryset(
            request=request,
            content_type_id=str(scope.current_folder.content_type_id) if scope.current_folder.content_type_id else None,
            object_id=scope.current_folder.object_id,
            current_folder=scope.current_folder,
            query=query,
        )
        return [
            _serialize_folder_item(folder, query=query, current_folder=scope.current_folder)
            for folder in folders.order_by("name")
        ]

    if scope.linked_object or scope.content_type:
        folders = _build_visible_folders_queryset(
            request=request,
            content_type_id=str(scope.content_type.id) if scope.content_type else None,
            object_id=str(scope.linked_object.pk) if scope.linked_object else None,
            current_folder=None,
            query=query,
        )
        return [_serialize_folder_item(folder, query=query) for folder in folders.order_by("name")]

    root_folders = _build_visible_folders_queryset(
        request=request,
        content_type_id=None,
        object_id=None,
        current_folder=None,
        query=query,
    )
    return [
        _serialize_folder_item(folder, query=query) for folder in root_folders.order_by("name")
    ]


def _build_file_browser_url(
    request: HttpRequest,
    *,
    module_id: str | None = None,
    content_type_id: str | None = None,
    object_id: str | None = None,
    folder_id: str | None = None,
) -> str:
    params = request.GET.copy()
    for key in [
        "module_id",
        "content_type_id",
        "content_type",
        "object_id",
        "folder_id",
        "folder",
        "page",
        "_render_id",
    ]:
        params.pop(key, None)

    if module_id:
        params["module_id"] = module_id
    if content_type_id:
        params["content_type_id"] = content_type_id
    if object_id:
        params["object_id"] = object_id
    if folder_id:
        params["folder_id"] = folder_id

    query_string = params.urlencode()
    if query_string:
        return f"{request.path}?{query_string}"
    return request.path


def _get_scoped_root_folder(scope: FileBrowserScope) -> FileFolder | None:
    if scope.current_folder is None:
        return None

    folder_chain = [*scope.current_folder.parents, scope.current_folder]

    if scope.linked_object is not None:
        linked_object_id = str(scope.linked_object.pk)
        for folder in folder_chain:
            if (folder.object_id or None) == linked_object_id:
                return folder

    if scope.content_type is not None:
        for folder in folder_chain:
            if folder.content_type_id == scope.content_type.id and not folder.object_id:
                return folder

    return None


def _build_scope_breadcrumbs(
    request: HttpRequest,
    scope: FileBrowserScope,
    *,
    hide_ancestor_folders: bool = False,
) -> list[dict]:
    if scope.current_folder:
        if hide_ancestor_folders:
            scoped_root = _get_scoped_root_folder(scope)
            if scoped_root is None or scoped_root.id == scope.current_folder.id:
                return [{"label": _get_folder_display_name(scope.current_folder), "active": True}]

            breadcrumbs: list[dict] = []
            include_folder = False
            for folder in [*scope.current_folder.parents, scope.current_folder]:
                if folder.id == scoped_root.id:
                    include_folder = True

                if not include_folder:
                    continue

                breadcrumbs.append(
                    {
                        "label": _get_folder_display_name(folder),
                        "url": _build_file_browser_url(request, folder_id=str(folder.id)),
                        "active": folder.id == scope.current_folder.id,
                    }
                )

            if breadcrumbs:
                breadcrumbs[-1].pop("url", None)
            return breadcrumbs

        breadcrumbs: list[dict] = [
            {
                "label": "Root",
                "url": _build_file_browser_url(request),
                "active": False,
            }
        ]
        for folder in scope.current_folder.parents:
            breadcrumbs.append(
                {
                    "label": _get_folder_display_name(folder),
                    "url": _build_file_browser_url(request, folder_id=str(folder.id)),
                    "active": False,
                }
            )
        breadcrumbs.append({"label": _get_folder_display_name(scope.current_folder), "active": True})
        return breadcrumbs

    breadcrumbs: list[dict] = [
        {
            "label": "Root",
            "url": _build_file_browser_url(request),
            "active": True,
        }
    ]

    if scope.linked_object:
        if hide_ancestor_folders:
            return [{"label": str(scope.linked_object), "active": True}]

    return breadcrumbs


def _get_descendant_folder_ids(folder: FileFolder) -> list[int]:
    descendants: list[int] = []
    stack = list(FileFolder.objects.filter(parent=folder).only("id"))
    while stack:
        current = stack.pop()
        descendants.append(current.id)
        stack.extend(FileFolder.objects.filter(parent=current).only("id"))
    return descendants


def _render_file_browser(
    request: HttpRequest,
    *,
    module_id: str | None = None,
    content_type_id: str | None = None,
    object_id: str | None = None,
    folder_id: str | None = None,
) -> HttpResponse:
    file_content_type = _get_file_content_type()
    query = request.GET.get("q") or None
    hide_ancestor_folders = request.GET.get("hide_ancestor_folders") == "true"

    module_id = _coerce_query_value(module_id or request.GET.get("module_id"))
    content_type_id = _coerce_query_value(content_type_id or _get_request_value(request, "content_type_id", "content_type"))
    object_id = _coerce_query_value(object_id or request.GET.get("object_id"))
    folder_id = _coerce_query_value(folder_id or _get_request_value(request, "folder_id", "folder"))

    linked_content_type, linked_object = _get_object_scope(content_type_id, object_id)
    if linked_object and not _check_linked_file_permission(
        request=request,
        linked_object=linked_object,
        files_field=_get_linked_object_files_field(linked_object),
        operation="view",
        ):
        return HttpResponse(status=403)

    current_folder = None
    if folder_id:
        current_folder = get_object_or_404(FileFolder, id=folder_id)
        if not _user_can_view_folder(request, current_folder):
            return HttpResponse(status=403)
    elif linked_object:
        current_folder = ensure_folder_hierarchy_for_object(
            linked_object,
            created_by=request.user,
            updated_by=request.user,
        )
        hide_ancestor_folders = True
    elif linked_content_type:
        current_folder = _get_model_scope_folder(linked_content_type)

    if current_folder and current_folder.content_type_id and not linked_content_type:
        linked_content_type = current_folder.content_type
    if current_folder and current_folder.object_id and linked_object is None:
        linked_object = _get_folder_linked_object(current_folder)

    scope = FileBrowserScope(
        content_type=linked_content_type,
        linked_object=linked_object,
        current_folder=current_folder,
    )

    visible_files = _build_visible_files_queryset(
        request=request,
        content_type_id=content_type_id,
        object_id=object_id,
        current_folder=current_folder,
        query=query,
    )
    navigation_items = _build_navigation_items(request=request, scope=scope, query=query)

    scoped_content_type_id = (
        str(linked_content_type.id)
        if linked_content_type
        else (str(current_folder.content_type_id) if current_folder and current_folder.content_type_id else None)
    )
    scoped_object_id = (
        str(linked_object.pk)
        if linked_object
        else (current_folder.object_id if current_folder and current_folder.object_id else None)
    )
    folder_context = {
        "current_folder": current_folder,
        "scoped_content_type_id": scoped_content_type_id,
        "scoped_object_id": scoped_object_id,
        "breadcrumbs": _build_scope_breadcrumbs(request, scope, hide_ancestor_folders=hide_ancestor_folders),
        "navigation_items": navigation_items,
        "can_create_folder": (
            request.user.is_superuser
            or (
                linked_object is not None
                and _check_linked_file_permission(
                    request=request,
                    linked_object=linked_object,
                    files_field=_get_linked_object_files_field(linked_object),
                    operation="add",
                )
            )
            or (linked_object is None and request.user.has_perm("bloomerp.add_filefolder"))
        ),
    }
    folders_html = render(
        request,
        "components/files/folders.html",
        folder_context,
    ).content.decode("utf-8")

    component_args = {
        "scope-content-type-id": scoped_content_type_id or "",
        "scope-object-id": scoped_object_id or "",
        "folder-id": str(current_folder.id) if current_folder else "",
        "upload-url": reverse("components_files_upload"),
        "create-folder-url": reverse("components_files_create_folder"),
        "move-url": reverse("components_files_move_browser_item"),
        "rename-url": reverse("components_files_rename_folder"),
        "delete-url": reverse("components_files_delete_folder"),
        "hide-filters": ",".join(sorted(FILE_BROWSER_RESERVED_QUERY_KEYS)),
    }

    return dataview(
        request,
        file_content_type.id,
        base_queryset=visible_files,
        additional_reserved_query_keys=FILE_BROWSER_RESERVED_QUERY_KEYS,
        component_id="file-dataview-container",
        component_args=component_args,
        dataview_base_url=request.path,
        before_data_view=folders_html,
    )


@router.register(path="components/files/&<path:legacy_query>", name="components_files_legacy")
@router.register(path="components/files/", name="components_files")
@login_required
def files(request: HttpRequest, legacy_query: str | None = None) -> HttpResponse:
    _hydrate_legacy_querystring(request, legacy_query)
    return _render_file_browser(request)


def _get_target_folder(folder_id: str | None) -> FileFolder | None:
    if not folder_id:
        return None
    return get_object_or_404(FileFolder, id=folder_id)


def _get_file_for_mutation(request: HttpRequest) -> File:
    file_id = request.POST.get("file_id")
    file = get_object_or_404(File, id=file_id)
    if not _user_can_mutate_file(request, file, ("change", "add")):
        raise PermissionError
    return file


def _get_folder_descendants(folder: FileFolder) -> tuple[list[FileFolder], list[File]]:
    folders: list[FileFolder] = []
    files: dict[str, File] = {}
    stack = [folder]

    while stack:
        current = stack.pop()
        folders.append(current)
        for file in current.files.all():
            files[str(file.id)] = file
        children = list(FileFolder.objects.filter(parent=current).prefetch_related("files"))
        stack.extend(children)

    return folders, list(files.values())
