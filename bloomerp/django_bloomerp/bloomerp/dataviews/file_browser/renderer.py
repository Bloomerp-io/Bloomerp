from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.urls import reverse

from bloomerp.dataviews.definition import BaseDataviewRenderer
from bloomerp.dataviews.utils import resolve_string_query
from bloomerp.models.files.file import File
from bloomerp.dataviews.file_browser.config import (
    _get_related_fields,
    _resolve_content_type,
    _resolve_folder,
    _resolve_object,
)
from bloomerp.models.files.file_folder import FileFolder
from bloomerp.utils.models import string_search_on_qs


class FileBrowserRenderer(BaseDataviewRenderer):
    template_name = "dataviews/files.html"
    reserved_query_params = {"folder_id"}

    def _get_related_object_scopes(self, host_objects, host_content_type):
        configured = getattr(self.state.options, "related_fields", {}) or {}
        selected_fields = configured.get(
            host_content_type.pk,
            configured.get(str(host_content_type.pk), []),
        )
        host_model = host_content_type.model_class()
        if host_model is None or not selected_fields:
            return {}

        selectable_fields = set(_get_related_fields(host_model))
        selected_relations = []
        for field_name in selected_fields:
            if field_name not in selectable_fields:
                continue
            model_field = host_model._meta.get_field(field_name)
            accessor_name = (
                model_field.get_accessor_name()
                if hasattr(model_field, "get_accessor_name")
                else field_name
            )
            if accessor_name:
                selected_relations.append((field_name, accessor_name))

        if not selected_relations:
            return {}

        if hasattr(host_objects, "prefetch_related"):
            host_objects = host_objects.prefetch_related(
                *(accessor_name for _, accessor_name in selected_relations)
            )

        scopes: dict[int, set[str]] = {}
        for host_object in host_objects:
            for _, accessor_name in selected_relations:
                try:
                    related_value = getattr(host_object, accessor_name)
                except ObjectDoesNotExist:
                    continue

                related_objects = (
                    related_value.all()
                    if hasattr(related_value, "all")
                    else [related_value]
                )
                for related_object in related_objects:
                    if related_object is None or related_object.pk is None:
                        continue
                    content_type = ContentType.objects.get_for_model(related_object)
                    scopes.setdefault(content_type.pk, set()).add(
                        str(related_object.pk)
                    )
        return scopes

    @staticmethod
    def _scope_query(scopes: dict[int, set[str]]) -> Q:
        query = Q(pk__in=[])
        for content_type_id, object_ids in scopes.items():
            if object_ids:
                query |= Q(
                    content_type_id=content_type_id,
                    object_id__in=object_ids,
                )
        return query

    @staticmethod
    def _folder_is_in_scope(
        folder: FileFolder,
        scopes: dict[int, set[str]],
        *,
        root_content_type_id: int | None = None,
    ) -> bool:
        if folder.content_type_id is None:
            return False
        if folder.object_id is None:
            return folder.content_type_id == root_content_type_id
        return str(folder.object_id) in scopes.get(folder.content_type_id, set())

    def render(self, pagination=None, *, extra_context: dict[str, Any] | None = None):
        context = dict(extra_context or {})
        current_folder = _resolve_folder(self.state)

        if self.state.model != File:
            folders, files = self._get_related_model_items(current_folder)
        else:
            current_folder, folders, files = self._get_file_model_items(
                current_folder
            )

        context["folders"] = folders
        context["files"] = files
        context["current_folder"] = current_folder
        context["file_actions"] = File.bloomerp_config.object_actions or []
        context["folder_actions"] = FileFolder.bloomerp_config.object_actions or []
        context["file_content_type_id"] = ContentType.objects.get_for_model(File).pk
        context["folder_content_type_id"] = ContentType.objects.get_for_model(
            FileFolder
        ).pk
        context["upload_url"] = reverse("components_files_upload")
        context["move_url"] = reverse("components_files_move_browser_item")

        scope_content_type_id = None
        scope_object_id = None
        if current_folder is not None:
            scope_content_type_id = current_folder.content_type_id
            scope_object_id = current_folder.object_id
        elif self.state.model == File:
            scope_content_type = _resolve_content_type(self.state)
            scope_object = _resolve_object(self.state)
            scope_content_type_id = getattr(scope_content_type, "pk", None)
            scope_object_id = getattr(scope_object, "pk", None)

        context["scope_content_type_id"] = scope_content_type_id
        context["scope_object_id"] = scope_object_id
        return super().render(pagination, extra_context=context)

    def _get_file_model_items(self, current_folder):
        content_type = _resolve_content_type(self.state)
        linked_object = _resolve_object(self.state)
        related_scopes = {}

        if linked_object is not None and content_type is not None:
            object_id = str(linked_object.pk)
            related_scopes = self._get_related_object_scopes(
                [linked_object],
                content_type,
            )
            allowed_scopes = {content_type.pk: {object_id}}
            for related_content_type_id, related_object_ids in related_scopes.items():
                allowed_scopes.setdefault(related_content_type_id, set()).update(
                    related_object_ids
                )
            if current_folder is not None and not self._folder_is_in_scope(
                current_folder,
                allowed_scopes,
            ):
                current_folder = None

            if current_folder is None:
                current_folder = FileFolder.objects.filter(
                    content_type=content_type,
                    object_id=object_id,
                    protected=True,
                ).order_by("pk").first()

        if current_folder is not None:
            base_folders = FileFolder.objects.filter(parent=current_folder)
            is_host_folder = (
                linked_object is not None
                and content_type is not None
                and current_folder.content_type_id == content_type.pk
                and current_folder.object_id == str(linked_object.pk)
            )
            files = (
                self.state.queryset.filter(folder=current_folder)
                if is_host_folder
                else File.objects.filter(folder=current_folder)
            )
            if (
                is_host_folder
                and current_folder.protected
                and related_scopes
            ):
                related_query = self._scope_query(related_scopes)
                base_folders = FileFolder.objects.filter(
                    Q(parent=current_folder)
                    | (related_query & Q(protected=True))
                )
                files = (
                    files | File.objects.filter(related_query)
                ).distinct()
        else:
            folder_query = {"parent__isnull": True}
            if content_type is not None:
                folder_query["content_type"] = content_type
            base_folders = FileFolder.objects.filter(**folder_query)
            files = self.state.queryset.filter(folder__isnull=True)

        folders = string_search_on_qs(
            base_folders,
            resolve_string_query(self.state.request),
        )
        return current_folder, folders, files

    def _get_related_model_items(self, current_folder):
        object_ids = list(
            self.state.queryset.values_list("pk", flat=True)
        )
        object_id_strings = [str(object_id) for object_id in object_ids]
        scopes = {
            self.state.content_type_id: set(object_id_strings),
        }
        related_scopes = self._get_related_object_scopes(
            self.state.queryset,
            self.state.content_type,
        )
        for related_content_type_id, related_object_ids in related_scopes.items():
            scopes.setdefault(related_content_type_id, set()).update(
                related_object_ids
            )

        if current_folder is not None and not self._folder_is_in_scope(
            current_folder,
            scopes,
            root_content_type_id=self.state.content_type_id,
        ):
            current_folder = None

        if current_folder is not None:
            base_folders = FileFolder.objects.filter(parent=current_folder)
            files = File.objects.filter(folder=current_folder)
        else:
            related_query = self._scope_query(related_scopes)
            base_folders = FileFolder.objects.filter(
                Q(content_type=self.state.content_type) | related_query
            )
            files = File.objects.filter(self._scope_query(scopes))

        folders = string_search_on_qs(
            base_folders,
            resolve_string_query(self.state.request),
        )
        return folders, files
