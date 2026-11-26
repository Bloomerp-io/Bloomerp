from bloomerp.models.files.file_node import FileNode
from bloomerp.modules.file_management import FileManagement
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin
from django.contrib.contenttypes.models import ContentType
from django.views.generic import TemplateView


@router.register(
    path="files",
    route_type="module",
    name="Files",
    url_name="files",
    description="List of all files across the application.",
    modules=[FileManagement]
)
class BloomerpFileListView(BaseBloomerpView, DataviewMixin, TemplateView):
    dataview_sync_url = True
    model = FileNode
    module = None

    def get_dataview_content_type_id(self) -> int:
        """Render FileNode records in the library's dataview."""
        return ContentType.objects.get_for_model(FileNode).pk

    def has_permission(self) -> bool:
        """Require access to the new file-node library."""
        manager = UserPolicyManager(self.request.user)
        return manager.has_global_permission(
            model_or_content_type=FileNode,
            permissions=BloomerpPermission.VIEW
        )
