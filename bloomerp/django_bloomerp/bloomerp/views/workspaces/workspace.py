from bloomerp.workspaces.utils import has_access_to_workspace
from bloomerp.router import router
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.views.workspaces.base import BaseWorkspaceView
from django.views.generic import DetailView

@router.register(
    path="workspaces/<int:pk>/",
    name="workspace",
    route_type="app",

)
class BloomerpModuleWorkspace(BaseWorkspaceView, DetailView):
    model = Workspace 
    is_detail_view = False
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_workspace_template_context())
        return context
    
    def has_permission(self):
        return has_access_to_workspace(
            self.get_object(),
            self.request.user
        )

    def get_module_id(self) -> str | None:
        return self.get_object().module_id

    def get_workspace(self) -> Workspace | None:
        return self.get_object()
    
