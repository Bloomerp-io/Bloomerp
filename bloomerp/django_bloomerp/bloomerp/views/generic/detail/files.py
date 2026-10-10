"""Embed the file-node dataview scoped to the current record's references."""

import json
from typing import Any, ClassVar

from django.contrib.contenttypes.models import ContentType

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.files import File
from bloomerp.models.files.file_node import FileNode
from bloomerp.router import router

from .base import BaseBloomerpDetailView


@router.register(
    path="files",
    name="Files",
    url_name="files",
    description="Files for object for {model} model",
    route_type="detail",
    exclude_models=[File],
)
class BloomerpDetailFileListView(BaseBloomerpDetailView):
    """Show file nodes associated with the viewed object's content type and key."""

    template_name = "views/generic/detail/files.html"
    modules = None
    permission_fields: ClassVar[list[tuple[str, str]]] = [("files", "view")]

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
        return context
