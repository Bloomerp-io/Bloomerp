from django.shortcuts import redirect
from bloomerp.router import router
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.services.workspace_services import set_default_workspace
from bloomerp.views.workspace.base_workspace_view import BaseWorkspaceView
from bloomerp.views.mixins import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import DetailView
from django_htmx.http import HttpResponseClientRedirect

@router.register(
    path="workspaces/<int:pk>/",
    name="workspace",
    route_type="app",
)
class BloomerpModuleWorkspace(
    BaseWorkspaceView,
    PermissionRequiredMixin, 
    HtmxMixin, 
    LoginRequiredMixin, 
    DetailView
    ):
    
    model = Workspace 
    is_detail_view = False
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_workspace_template_context())
        return context

    def post(self, request, *args, **kwargs):
        workspace = self.get_object()

        if request.POST.get("action") == "set_default":
            try:
                set_default_workspace(workspace, request.user)
            except (PermissionError, ValueError):
                return self.handle_no_permission()

            redirect_url = workspace.get_absolute_url()
            if request.htmx:
                return HttpResponseClientRedirect(redirect_url)
            return redirect(redirect_url)

        return self.get(request, *args, **kwargs)
    
    def has_permission(self):
        obj:Workspace = self.get_object()
        if obj.user == self.request.user:
            return True
        
        return obj.shared_with.filter(pk=self.request.user.pk).exists()

    def get_module_id(self) -> str | None:
        return None

    def get_sub_module_id(self) -> str | None:
        return None

    def get_workspace(self) -> Workspace | None:
        return self.get_object()
    
