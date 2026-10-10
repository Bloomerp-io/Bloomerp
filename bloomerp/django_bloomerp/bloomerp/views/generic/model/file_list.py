from typing import Any

from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from django.contrib.contenttypes.models import ContentType
from django.views.generic import TemplateView


@router.register(
    path="files",
    route_type="app",
    name="Files",
    url_name="app",
    description="List of all files across the application.",
)
class BloomerpFileListView(BaseBloomerpView, TemplateView):
    template_name = "views/generic/model/bloomerp_file_list.html"
    model = FileNode
    module = None

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Embed the file-node browser for the library page."""
        context = super().get_context_data(**kwargs)
        context["file_content_type_id"] = ContentType.objects.get_for_model(FileNode).pk
        
        return context
    
    def has_permission(self) -> bool:
        """Require access to the new file-node library."""
        manager = UserPolicyManager(self.request.user)
        return manager.has_global_permission(
            model_or_content_type=FileNode,
            permissions=BloomerpPermission.VIEW
        )
