"""Embed the file-node dataview scoped to the current record's references."""

import json
from datetime import timedelta
from typing import Any, ClassVar

from bloomerp.files.access import FileAccessManager
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.files import FileNode
from bloomerp.permissions.definition import (
    AccessRule,
    PermissionToken,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .base import BaseBloomerpDetailView


@router.register(
    path="files",
    name="Files",
    url_name="files",
    description="Files for object for {model} model",
    route_type="detail",
    exclude_models=[FileNode],
)
class BloomerpDetailFileListView(BaseBloomerpDetailView):
    """Show file nodes associated with the viewed object's content type and key."""

    template_name = "views/generic/detail/files.html"
    modules = None
    permission_fields: ClassVar[list[tuple[str, str]]] = [("files", "view")]

    def has_permission(self) -> bool:
        """Delegate file access only when the files field is readable on this particular row."""
        return super().has_permission() and UserPolicyManager(self.request.user).has_access_to_object(
            self.get_object(), "view", fields=["files"],
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Serialize the reference scope as the dataview parser's JSON filter list."""
        context = super().get_context_data(**kwargs)
        content_type = ContentType.objects.get_for_model(self.object)
        reference_filter = Filter(
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
        )
        context["file_content_type_id"] = ContentType.objects.get_for_model(FileNode).pk
        context["filters"] = {
            "filter": json.dumps([reference_filter.model_dump(mode="json")])
        }
        context["args"] = {
            "hide_filters" "references"
        }
        readable_files = FileAccessManager(self.request.user).get_queryset(
            FileNode.objects.all(), related_object=self.object,
        )
        context["file_token"] = PermissionToken(
            model_label=FileNode._meta.label_lower,
            audience=str(self.request.user.pk),
            expiry=timezone.now() + timedelta(hours=1),
            rule=AccessRule(
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
            ),
        ).sign()
        return context
