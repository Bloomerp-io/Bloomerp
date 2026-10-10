"""Browse filtered file nodes through reference groups or physical parents."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import quote

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model, Q, QuerySet
from django.urls import reverse
from django.utils.translation import gettext as _

from bloomerp.dataviews.definition import BaseDataviewRenderer, DataviewPagination
from bloomerp.dataviews.file_browser.config import _get_related_fields, _resolve_object
from bloomerp.modules.definition import module_registry
from bloomerp.utils.models import string_search_on_qs

if TYPE_CHECKING:
    from bloomerp.models.files.file_node import FileNode
    from bloomerp.models.files.file_reference import FileReference


class FileBrowserRenderer(BaseDataviewRenderer):
    """Keep browsing inside the supplied scope and hide inaccessible reference labels."""

    template_name = "dataviews/files.html"
    reserved_query_params: ClassVar[set[str]] = {"folder_id", "virtual_path", "folder_type"}

    def _related_scopes(self, objects: Iterable[Model], content_type: ContentType) -> dict[int, set[str]]:
        """Collect configured related objects without changing the host query's scope."""
        configured = getattr(self.options, "related_fields", {}) or {}
        names = configured.get(content_type.pk, configured.get(str(content_type.pk), []))
        model = content_type.model_class()
        allowed = set(_get_related_fields(model)) if model else set()
        scopes: dict[int, set[str]] = {}
        for obj in objects:
            for name in names:
                if name not in allowed:
                    continue
                field = model._meta.get_field(name)
                accessor = field.get_accessor_name() if hasattr(field, "get_accessor_name") else name
                try:
                    value = getattr(obj, accessor)
                except ObjectDoesNotExist:
                    continue
                for related in value.all() if hasattr(value, "all") else [value]:
                    if related is not None:
                        ct = ContentType.objects.get_for_model(related)
                        scopes.setdefault(ct.pk, set()).add(str(related.pk))
        return scopes

    def _candidate_files(self) -> tuple[QuerySet[FileNode], dict[int, set[str]] | None]:
        """Use filtered nodes directly, or derive nodes from the filtered host collection."""
        from bloomerp.models.files.file_node import FileNode
        if self.state.model is FileNode:
            return self.state.queryset.filter(kind="FILE").distinct(), None
        objects = list(self.state.queryset)
        scopes = self._related_scopes(objects, self.state.content_type)
        scopes.setdefault(self.state.content_type_id, set()).update(str(obj.pk) for obj in objects)
        query = Q(pk__in=[])
        for ct, ids in scopes.items():
            query |= Q(references__content_type_id=ct, references__object_id__in=ids)
        files = FileNode.objects.filter(query, kind="FILE").distinct()
        return string_search_on_qs(files, self.state.query), scopes

    def _reference_target(self, reference: FileReference) -> Model | None:
        """Resolve and authorize each reference independently before displaying its owner."""
        from bloomerp.files.access import can_read_object_field
        obj = reference.content_object
        if obj is None:
            return None
        permission_obj = obj
        field = reference.application_field.field if reference.application_field else "files"
        if obj._meta.model_name == "comment" and reference.application_field:
            permission_obj, field = obj.content_object, "comments"
        if permission_obj is None or not can_read_object_field(self.state.request, permission_obj, field):
            return None
        return obj

    def _visible_entries(self) -> tuple[list[FileNode], dict[str, list[tuple[list[str], list[str], Model]]]]:
        """Build permitted reference paths, retaining only readable candidate files."""
        from bloomerp.files.access import FileAccessManager
        candidates, scopes = self._candidate_files()
        access = FileAccessManager(self.state.request.user)
        files: list[FileNode] = []
        entries: dict[str, list[tuple[list[str], list[str], Model]]] = {}
        for file in candidates.prefetch_related("references__content_type", "references__application_field"):
            references = list(file.references.all())
            paths: list[tuple[list[str], list[str], Model]] = []
            owners: dict[tuple[int, str, int | None], dict[str, Any]] = {}
            for reference in references:
                if scopes is not None and reference.object_id not in scopes.get(reference.content_type_id, set()):
                    continue
                obj = self._reference_target(reference)
                if obj is None:
                    continue
                field = reference.application_field
                url = obj.get_absolute_url() if hasattr(obj, "get_absolute_url") else ""
                if field and url:
                    url = f"{url}#{quote(field.field)}"
                owners[(reference.content_type_id, reference.object_id, reference.application_field_id)] = {
                    "label": str(obj), "url": url, "object_id": str(obj.pk),
                    "content_type_id": reference.content_type_id,
                    "field_label": str(field.title) if field else "",
                }
                module = module_registry.get_module_for_model(type(obj))
                module_id = (module.full_id or module.code) if module else "__other__"
                path = [module_id, str(reference.content_type_id), str(obj.pk)]
                labels = [module.localized_name if module else _("Other"), str(obj._meta.verbose_name_plural), str(obj)]
                if not any(existing[0] == path for existing in paths):
                    paths.append((path, labels, obj))
            if paths or (scopes is None and access.can_read_file_node(file)):
                files.append(file)
                entries[str(file.pk)] = paths
                # Only display owners whose particular reference is readable.
                file.browser_owners = list(owners.values())
                file.browser_unassigned = not references
        return files, entries

    @staticmethod
    def _virtual_path(raw: str) -> list[str]:
        """Decode navigation tokens without treating them as model filters."""
        try:
            value = json.loads(raw or "[]")
        except (ValueError, TypeError):
            return ["__invalid__"]
        if not isinstance(value, list) or len(value) > 3 or any(not isinstance(part, str) for part in value):
            return ["__invalid__"]
        return value

    def _virtual_context(self, files: list[FileNode], entries: dict[str, list[tuple[list[str], list[str], Model]]]) -> dict[str, Any]:
        """Generate module, model and object folders without storing physical nodes."""
        from bloomerp.models.files.file_node import FileNode
        host = _resolve_object(self.state) if self.state.model is FileNode else None
        path = self._virtual_path(self.state.request.GET.get("virtual_path", ""))
        folders: dict[str, dict[str, Any]] = {}
        shown: dict[str, FileNode] = {}
        breadcrumbs = [{"name": _("Files"), "path": "[]"}]
        labels_for_path: list[str] = []
        upload_target = host
        for file in files:
            if host is not None:
                shown[str(file.pk)] = file
                continue
            if file.browser_unassigned:
                if path == ["__unassigned__"]:
                    shown[str(file.pk)] = file
                    labels_for_path = [_("Unassigned")]
                elif not path:
                    folders["__unassigned__"] = {"name": _("Unassigned"), "path": '["__unassigned__"]'}
            for entry_path, labels, obj in entries[str(file.pk)]:
                if entry_path[:len(path)] != path:
                    continue
                labels_for_path = labels[:len(path)]
                if len(path) == 3:
                    shown[str(file.pk)] = file
                    upload_target = obj
                else:
                    child_path = entry_path[:len(path) + 1]
                    token = json.dumps(child_path)
                    folders[token] = {"name": labels[len(path)], "path": token}
        for index, label in enumerate(labels_for_path):
            breadcrumbs.append({"name": label, "path": json.dumps(path[:index + 1])})
        valid_root = not path or path == ["__unassigned__"]
        return {
            "folders": sorted(folders.values(), key=lambda folder: folder["name"].casefold()),
            "files": list(shown.values()), "breadcrumbs": breadcrumbs,
            "upload_target": upload_target,
            "allow_unassigned_upload": valid_root and self.state.model is FileNode and host is None,
        }

    def _physical_context(self, files: list[FileNode]) -> dict[str, Any]:
        """Show physical parents containing scoped files or explicitly accessible empty folders."""
        from bloomerp.models.files.file_node import FileNode
        all_folders = {str(folder.pk): folder for folder in FileNode.objects.filter(kind="FOLDER")}
        visible: set[str] = set()
        for file in files:
            parent = str(file.parent_id) if file.parent_id else ""
            while parent and parent in all_folders and parent not in visible:
                visible.add(parent)
                parent_id = all_folders[parent].parent_id
                parent = str(parent_id) if parent_id else ""
        if self.state.model is FileNode:
            visible.update(str(pk) for pk in self.state.queryset.filter(kind="FOLDER").values_list("pk", flat=True))
        current = self.state.request.GET.get("folder_id", "")
        breadcrumbs = [{"name": _("Files"), "folder_id": ""}]
        chain: list[dict[str, str]] = []
        parent = current
        seen: set[str] = set()
        while parent in visible and parent not in seen:
            seen.add(parent)
            folder = all_folders[parent]
            chain.append({"name": folder.name, "folder_id": parent})
            parent = str(folder.parent_id) if folder.parent_id else ""
        breadcrumbs.extend(reversed(chain))
        valid = not current or current in visible
        return {
            "folders": [
                {"name": folder.name, "folder_id": pk}
                for pk, folder in all_folders.items()
                if valid and pk in visible and (str(folder.parent_id) if folder.parent_id else "") == current
            ],
            "files": [file for file in files if valid and (str(file.parent_id) if file.parent_id else "") == current],
            "breadcrumbs": breadcrumbs, "upload_target": None,
            "allow_unassigned_upload": not current and self.state.model is FileNode,
        }

    def render(self, pagination: DataviewPagination | None = None, *, extra_context: dict[str, Any] | None = None) -> str:
        """Render navigation and node actions without exposing legacy folder mutations."""
        from bloomerp.files.access import FileAccessManager
        from bloomerp.models.files.file_node import FileNode
        files, entries = self._visible_entries()
        mode = self.state.request.GET.get("folder_type", getattr(self.options, "folder_type", "virtual"))
        mode = mode if mode in {"virtual", "physical"} else "virtual"
        context = self._physical_context(files) if mode == "physical" else self._virtual_context(files, entries)
        target = context.pop("upload_target")
        access = FileAccessManager(self.state.request.user)
        can_upload = access.has_access_to_linked_object(target, "add") if target is not None else False
        if context.pop("allow_unassigned_upload"):
            from bloomerp.permissions.manager import UserPolicyManager
            manager = UserPolicyManager(self.state.request.user)
            can_upload = all(manager.has_global_permission(FileNode, perm) for perm in ("add", "view"))
        context.update({
            "folder_type": mode, "can_upload": can_upload,
            "upload_url": reverse("api_assistant_file_upload"),
            "upload_model_label": target._meta.label if target is not None else "",
            "upload_object_id": str(target.pk) if target is not None else "",
            "file_actions": FileNode.bloomerp_config.object_actions or [],
            "file_content_type_id": ContentType.objects.get_for_model(FileNode).pk,
        })
        context.update(extra_context or {})
        return super().render(pagination or DataviewPagination(self.state.queryset), extra_context=context)
