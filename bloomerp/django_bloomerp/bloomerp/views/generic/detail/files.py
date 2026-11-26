"""Embed the file-node dataview scoped to the current record's references."""

from typing import ClassVar

from django.contrib.contenttypes.models import ContentType

from bloomerp.files.access import FileAccessManager
from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.models.files import FileNode
from bloomerp.permissions.definition import (
    AccessRule,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.tokens import RequestToken
from bloomerp.views.mixins.dataview_mixin import DataviewMixin

from .base import BaseBloomerpDetailView


@router.register(
    path="files",
    name="Files",
    url_name="files",
    description="Files for object for {model} model",
    route_type="detail",
    exclude_models=[FileNode],
)
class BloomerpDetailFileListView(DataviewMixin, BaseBloomerpDetailView):
    """Show file nodes associated with the viewed object's content type and key."""

    dataview_hide_filters = True
    dataview_sync_url = True
    modules = None
    permission_fields: ClassVar[list[tuple[str, str]]] = [("files", "view")]

    def has_permission(self) -> bool:
        """Delegate file access only when the files field is readable on this particular row."""
        return super().has_permission() and UserPolicyManager(self.request.user).has_access_to_object(
            self.get_object(), "view", fields=["files"],
        )

    def get_dataview_content_type_id(self) -> int:
        """Render file-node records in the current object's Files tab."""
        return ContentType.objects.get_for_model(FileNode).pk

    def get_dataview_filters(self) -> Filters:
        """Match files with a reference to the current record."""
        content_type = ContentType.objects.get_for_model(self.object)
        return [Filter(
            connector="AND",
            conditions=[
                FilterCondition(
                    field_path="references__content_type",
                    lookup_id="equals",
                    value=content_type.pk,
                ),
                FilterCondition(
                    field_path="references__object_id",
                    lookup_id="equals",
                    value=str(self.object.pk),
                ),
            ],
        )]

    def get_dataview_request_token(self) -> RequestToken:
        """Delegate read access to files the viewer may read through this record."""
        reference_filter = self.get_dataview_filters()[0]
        readable_files = FileAccessManager(self.request.user).get_queryset(
            FileNode.objects.all(), related_object=self.object,
        )
        return RequestToken(
            policies={FileNode: AccessRule(
                row_permissions=[RowPolicyRuleContent(
                    permissions=["view"],
                    conditions=[
                        *reference_filter.conditions,
                        FilterCondition(
                            field_path="id", lookup_id="values_in",
                            value=[str(pk) for pk in readable_files.values_list("pk", flat=True).distinct()],
                    )],
                )],
                field_permissions={field: ["view"] for field in (
                    "id", "name", "kind", "content", "meta", "datetime_created",
                )},
            )},
        )
