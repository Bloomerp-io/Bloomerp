import json
import uuid
from urllib.parse import parse_qs
from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, render

from bloomerp.components.application_fields.filters import FILTERABLE_FIELD_TYPES
from bloomerp.components.objects.dataview import _build_pagination_range
from bloomerp.components.objects.dataview import _format_applied_filters
from bloomerp.models import ApplicationField, File, FileFolder
from bloomerp.models.users.user_list_view_preference import PageSize, UserListViewPreference
from bloomerp.router import router
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.services.permission_services import create_permission_str
from bloomerp.utils.filters import filter_model


FILE_BROWSER_VIEW_TYPES = ("table", "card")
FILE_BROWSER_FIXED_COLUMNS = (
    "name",
    "content_object",
    "folder",
    "size_str",
    "datetime_updated",
)
FILE_BROWSER_FILTER_FIELDS = (
    "name",
    "content_type",
    "object_id",
    "created_by",
    "datetime_created",
    "datetime_updated",
)
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


def _get_file_preference(user, content_type: ContentType) -> UserListViewPreference:
    preference, _ = UserListViewPreference.objects.get_or_create(
        user=user,
        content_type=content_type,
    )
    if preference.view_type not in FILE_BROWSER_VIEW_TYPES:
        preference.view_type = FILE_BROWSER_VIEW_TYPES[0]
        preference.save(update_fields=["view_type"])
    return preference


def _sanitize_filter_params(query_params) -> dict[str, list[str]]:
    allowed = set(FILE_BROWSER_FILTER_FIELDS)
    sanitized: dict[str, list[str]] = {}

    for key in query_params.keys():
        if key in FILE_BROWSER_RESERVED_QUERY_KEYS:
            continue

        base_key = key.split("__", 1)[0]
        if base_key not in allowed:
            continue

        values = [value for value in query_params.getlist(key) if value != ""]
        if values:
            sanitized[key] = values

    return sanitized


def _get_filter_section(request: HttpRequest, file_content_type_id: int) -> str:
    application_fields = ApplicationField.get_for_content_type_id(file_content_type_id).filter(
        field__in=FILE_BROWSER_FILTER_FIELDS,
        field_type__in=FILTERABLE_FIELD_TYPES,
    )
    return render(
        request,
        "components/filters/init.html",
        {
            "content_type_id": file_content_type_id,
            "application_fields": application_fields,
            "selected_application_field": None,
            "html_content": "",
        },
    ).content.decode("utf-8")


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

    return folder.name


def _normalize_folder_label(folder: FileFolder, current_folder: FileFolder | None) -> str:
    if current_folder and folder.parent_id == current_folder.id:
        return _get_folder_display_name(folder)
    return _folder_path(folder)


def _get_folder_choices(
    *,
    folders: QuerySet[FileFolder],
    current_folder: FileFolder | None,
) -> list[dict[str, str]]:
    return [
        {
            "id": str(folder.id),
            "label": _normalize_folder_label(folder, current_folder),
        }
        for folder in folders.order_by("name").distinct()
    ]


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

    sanitized_filters = _sanitize_filter_params(request.GET)
    if sanitized_filters:
        mutable_get = request.GET.copy()
        for key in list(mutable_get.keys()):
            if key not in FILE_BROWSER_RESERVED_QUERY_KEYS and key not in sanitized_filters:
                mutable_get.pop(key, None)

        queryset = filter_model(File, mutable_get, queryset)

    return queryset.order_by("name")


def _serialize_file_row(request: HttpRequest, file: File, current_folder: FileFolder | None) -> dict:
    folder_label = current_folder.name if current_folder else (file.folder.name if file.folder_id else "Root")
    linked_object = _get_file_linked_object(file)

    return {
        "id": str(file.id),
        "name": file.name or str(file),
        "kind": "file",
        "folder_label": folder_label,
        "size": file.size_str,
        "datetime_updated": file.datetime_updated,
        "content_object_label": str(linked_object) if linked_object else "Unlinked",
        "content_object_url": getattr(linked_object, "get_absolute_url", None) if linked_object else None,
        "content_type_label": file.content_type.name if file.content_type_id else "Unlinked",
        "view_url": file.url if file.file else None,
        "download_url": file.url if file.file else None,
        "rename_allowed": file.persisted and _user_can_mutate_file(request, file, ("change", "add")),
        "move_allowed": file.persisted and _user_can_mutate_file(request, file, ("change", "add")),
        "delete_allowed": file.persisted and _user_can_mutate_file(request, file, ("delete",)),
        "file": file,
    }


def _prepare_file_rows(
    request: HttpRequest,
    queryset: QuerySet[File],
    current_folder: FileFolder | None,
) -> list[dict]:
    return [_serialize_file_row(request, file, current_folder) for file in queryset]


def _prepare_file_cards(
    request: HttpRequest,
    queryset: QuerySet[File],
    current_folder: FileFolder | None,
) -> list[dict]:
    cards: list[dict] = []
    for file in queryset:
        linked_object = _get_file_linked_object(file)
        cards.append(
            {
                "id": str(file.id),
                "name": file.name or str(file),
                "size": file.size_str,
                "updated_at": file.datetime_updated,
                "object_label": str(linked_object) if linked_object else "Unlinked",
                "object_url": getattr(linked_object, "get_absolute_url", None) if linked_object else None,
                "folder_label": (
                    current_folder.name
                    if current_folder
                    else (file.folder.name if file.folder_id else "Root")
                ),
                "view_url": file.url if file.file else None,
                "download_url": file.url if file.file else None,
                "rename_allowed": file.persisted and _user_can_mutate_file(request, file, ("change", "add")),
                "move_allowed": file.persisted and _user_can_mutate_file(request, file, ("change", "add")),
                "delete_allowed": file.persisted and _user_can_mutate_file(request, file, ("delete",)),
                "file": file,
            }
        )
    return cards


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
    render_id = request.GET.get("_render_id") or str(uuid.uuid4())
    data_section_id = f"file-browser-data-section-{render_id}"
    file_content_type = _get_file_content_type()
    preference = _get_file_preference(request.user, file_content_type)
    query = request.GET.get("q") or None
    page = request.GET.get("page", 1)
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

    paginator = Paginator(visible_files, preference.page_size or PageSize.SIZE_25)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages or 1)

    page_querystring = request.GET.copy()
    page_querystring.pop("page", None)
    search_querystring = request.GET.copy()
    search_querystring.pop("page", None)
    search_querystring.pop("q", None)
    applied_filter_query = request.GET.copy()
    for key in list(applied_filter_query.keys()):
        if key in FILE_BROWSER_RESERVED_QUERY_KEYS:
            applied_filter_query.pop(key, None)

    current_url = request.get_full_path()
    available_move_folders = FileFolder.objects.all()
    if linked_content_type:
        available_move_folders = available_move_folders.filter(content_type=linked_content_type)
    else:
        available_move_folders = available_move_folders.filter(content_type__isnull=True)
    if linked_object:
        available_move_folders = available_move_folders.filter(object_id=str(linked_object.pk))
    else:
        available_move_folders = available_move_folders.filter(object_id__isnull=True)
    if query or hide_ancestor_folders:
        folder_choices = []
    else:
        available_move_folder_ids = [
            folder.id
            for folder in available_move_folders.distinct()
            if _user_can_view_folder(request, folder)
        ]
        folder_choices = _get_folder_choices(
            folders=FileFolder.objects.filter(id__in=available_move_folder_ids),
            current_folder=current_folder,
        )

    context = {
        "render_id": render_id,
        "data_section_id": data_section_id,
        "current_url": current_url,
        "base_url": request.path,
        "module_id": module_id,
        "content_type_id": (
            str(linked_content_type.id)
            if linked_content_type
            else (str(current_folder.content_type_id) if current_folder and current_folder.content_type_id else None)
        ),
        "object_id": (
            str(linked_object.pk)
            if linked_object
            else (current_folder.object_id if current_folder and current_folder.object_id else None)
        ),
        "file_content_type_id": file_content_type.id,
        "preference": preference,
        "view_types": FILE_BROWSER_VIEW_TYPES,
        "fixed_columns": FILE_BROWSER_FIXED_COLUMNS,
        "filter_section": _get_filter_section(request, file_content_type.id),
        "search_query": query or "",
        "search_querystring": search_querystring.urlencode(),
        "page_querystring": page_querystring.urlencode(),
        "current_folder": current_folder,
        "breadcrumbs": _build_scope_breadcrumbs(request, scope, hide_ancestor_folders=hide_ancestor_folders),
        "navigation_items": navigation_items,
        "page_obj": page_obj,
        "files": page_obj.object_list,
        "file_rows": _prepare_file_rows(request, page_obj.object_list, current_folder),
        "file_cards": _prepare_file_cards(request, page_obj.object_list, current_folder),
        "pagination_pages": _build_pagination_range(page_obj),
        "applied_filters": _format_applied_filters(applied_filter_query),
        "folder_options_json": json.dumps(folder_choices),
        "target": getattr(getattr(request, "htmx", None), "target", None),
        "is_data_section_target": getattr(getattr(request, "htmx", None), "target", None) == data_section_id,
        "sync_url": request.headers.get("X-Bloomerp-Sync-Url", "false").lower() == "true",
    }

    return render(request, "components/files/browser.html", context)


@router.register(path="components/files/&<path:legacy_query>", name="components_files_legacy")
@router.register(path="components/files/", name="components_files")
@login_required
def files(request: HttpRequest, legacy_query: str | None = None) -> HttpResponse:
    _hydrate_legacy_querystring(request, legacy_query)
    return _render_file_browser(request)


@router.register(path="components/files/preference/", name="components_files_preference")
@login_required
def change_file_browser_preference(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    file_content_type = _get_file_content_type()
    preference = _get_file_preference(request.user, file_content_type)

    view_type = request.POST.get("view_type")
    if view_type:
        if view_type not in FILE_BROWSER_VIEW_TYPES:
            return HttpResponse("Invalid view type", status=400)
        preference.view_type = view_type
        preference.save(update_fields=["view_type"])

    return JsonResponse({"ok": True, "view_type": preference.view_type})


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


def _folder_accepts_file(folder: FileFolder | None, file: File) -> bool:
    if folder is None:
        return True

    return (
        folder.content_type_id == file.content_type_id
        and (folder.object_id or None) == (file.object_id or None)
    )


@router.register(path="components/files/upload/", name="components_files_upload")
@login_required
def upload_files(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    content_type_id = _coerce_query_value(request.POST.get("content_type_id"))
    object_id = _coerce_query_value(request.POST.get("object_id"))
    folder_id = _coerce_query_value(request.POST.get("folder_id"))

    linked_content_type, linked_object = _get_object_scope(content_type_id, object_id)
    files_field = _get_linked_object_files_field(linked_object) if linked_object else None
    requested_object_id = str(linked_object.pk) if linked_object else None

    if linked_object:
        if not _check_linked_file_permission(
            request=request,
            linked_object=linked_object,
            files_field=files_field,
            operation="add",
        ):
            return HttpResponse(status=403)
    elif not request.user.has_perm("bloomerp.add_file"):
        return HttpResponse(status=403)

    target_folder = _get_target_folder(folder_id)
    if target_folder and (
        target_folder.content_type_id != (linked_content_type.id if linked_content_type else None)
        or (target_folder.object_id or None) != requested_object_id
    ):
        return HttpResponse("Selected folder has a different scope", status=400)

    uploaded_files = request.FILES.getlist("files")
    for uploaded in uploaded_files:
        file = File.objects.create(
            file=uploaded,
            name=uploaded.name,
            persisted=True,
            content_type=linked_content_type,
            object_id=requested_object_id,
            folder=target_folder,
            created_by=request.user,
            updated_by=request.user,
        )

    return JsonResponse({"ok": True, "count": len(uploaded_files)})


@router.register(path="components/files/folders/create/", name="components_files_create_folder")
@login_required
def create_file_folder(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    content_type_id = _coerce_query_value(request.POST.get("content_type_id"))
    object_id = _coerce_query_value(request.POST.get("object_id"))
    parent_folder = _get_target_folder(_coerce_query_value(request.POST.get("parent_folder_id")))

    linked_content_type, linked_object = _get_object_scope(content_type_id, object_id)
    files_field = _get_linked_object_files_field(linked_object) if linked_object else None

    if linked_object:
        if not _check_linked_file_permission(
            request=request,
            linked_object=linked_object,
            files_field=files_field,
            operation="add",
        ):
            return HttpResponse(status=403)
    elif not request.user.has_perm("bloomerp.add_filefolder"):
        return HttpResponse(status=403)

    name = (request.POST.get("name") or "").strip()
    if not name:
        return HttpResponse("Folder name is required", status=400)

    folder_content_type = linked_content_type or (parent_folder.content_type if parent_folder else None)
    folder_object_id = (
        str(linked_object.pk)
        if linked_object
        else (parent_folder.object_id if parent_folder else None)
    )

    folder = FileFolder(
        name=name,
        parent=parent_folder,
        content_type=folder_content_type,
        object_id=folder_object_id,
        created_by=request.user,
        updated_by=request.user,
    )
    try:
        folder.save()
    except ValidationError as exc:
        return HttpResponse(exc.messages[0], status=400)
    return JsonResponse({"ok": True, "folder_id": folder.id, "name": folder.name})


@router.register(path="components/files/move/", name="components_files_move")
@login_required
def move_file_browser_item(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    item_type = request.POST.get("item_type")
    target_folder = _get_target_folder(_coerce_query_value(request.POST.get("target_folder_id")))

    if item_type == "file":
        file = _get_file_for_mutation(request)
        if not _folder_accepts_file(target_folder, file):
            return HttpResponse("File cannot be moved into a folder with a different scope", status=400)
        file.folder = target_folder
        file.updated_by = request.user
        file.save(update_fields=["folder", "updated_by"])
        return JsonResponse({"ok": True})

    if item_type == "folder":
        folder = get_object_or_404(FileFolder, id=request.POST.get("folder_id"))
        if not request.user.has_perm("bloomerp.change_filefolder"):
            return HttpResponse(status=403)

        if target_folder and target_folder.id == folder.id:
            return HttpResponse("Cannot move a folder into itself", status=400)

        ancestor = target_folder
        while ancestor is not None:
            if ancestor.id == folder.id:
                return HttpResponse("Cannot move a folder into its own descendant", status=400)
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
        return JsonResponse({"ok": True})

    return HttpResponse("Unsupported item type", status=400)


@router.register(path="components/files/rename/", name="components_files_rename")
@login_required
def rename_file_browser_item(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    item_type = request.POST.get("item_type")
    name = (request.POST.get("name") or "").strip()
    if not name:
        return HttpResponse("Name is required", status=400)

    if item_type == "file":
        try:
            file = _get_file_for_mutation(request)
        except PermissionError:
            return HttpResponse(status=403)

        file.name = name
        file.updated_by = request.user
        file.save(update_fields=["name", "updated_by"])
        return JsonResponse({"ok": True, "name": file.name})

    if item_type == "folder":
        folder = get_object_or_404(FileFolder, id=request.POST.get("folder_id"))
        if not request.user.has_perm("bloomerp.change_filefolder"):
            return HttpResponse(status=403)

        folder.name = name
        folder.updated_by = request.user
        folder.save(update_fields=["name", "updated_by"])
        return JsonResponse({"ok": True, "name": folder.name})

    return HttpResponse("Unsupported item type", status=400)


@router.register(path="components/files/delete-preview/", name="components_files_delete_preview")
@login_required
def delete_file_browser_item_preview(request: HttpRequest) -> HttpResponse:
    item_type = request.GET.get("item_type")

    if item_type == "file":
        file = get_object_or_404(File, id=request.GET.get("file_id"))
        if not _user_can_mutate_file(request, file, ("delete",)):
            return HttpResponse(status=403)
        return JsonResponse({"ok": True, "files": 1, "folders": 0})

    if item_type == "folder":
        folder = get_object_or_404(FileFolder, id=request.GET.get("folder_id"))
        descendant_folders, descendant_files = _get_folder_descendants(folder)
        can_delete_files = all(
            _user_can_mutate_file(request, file, ("delete",))
            for file in descendant_files
        )
        can_delete_folder = request.user.has_perm("bloomerp.delete_filefolder")
        if not (can_delete_files and can_delete_folder):
            return HttpResponse(status=403)

        return JsonResponse(
            {
                "ok": True,
                "files": len(descendant_files),
                "folders": len(descendant_folders),
            }
        )

    return HttpResponse("Unsupported item type", status=400)


@router.register(path="components/files/delete/", name="components_files_delete")
@login_required
def delete_file_browser_item(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    item_type = request.POST.get("item_type")

    if item_type == "file":
        file = get_object_or_404(File, id=request.POST.get("file_id"))
        if not _user_can_mutate_file(request, file, ("delete",)):
            return HttpResponse(status=403)
        file.delete()
        return JsonResponse({"ok": True})

    if item_type == "folder":
        folder = get_object_or_404(FileFolder, id=request.POST.get("folder_id"))
        descendant_folders, descendant_files = _get_folder_descendants(folder)
        can_delete_files = all(
            _user_can_mutate_file(request, file, ("delete",))
            for file in descendant_files
        )
        can_delete_folder = request.user.has_perm("bloomerp.delete_filefolder")
        if not (can_delete_files and can_delete_folder):
            return HttpResponse(status=403)

        folder.delete()
        return JsonResponse(
            {
                "ok": True,
                "files_deleted": len(descendant_files),
                "folders_deleted": len(descendant_folders),
            }
        )

    return HttpResponse("Unsupported item type", status=400)
