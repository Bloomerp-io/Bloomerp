from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView

from bloomerp.router import router
from bloomerp.utils.models import get_create_view_url
from bloomerp.views.mixins import HtmxMixin
from bloomerp.views.workspace.base_workspace_view import BaseWorkspaceView
from bloomerp.models.workspaces.workspace import Workspace


@router.register(
    path="workspaces/",
    url_name="my_workspaces",
    route_type="app",
    name="My workspaces",
    description="List of your workspaces"
)
class MyWorkspacesView(BaseWorkspaceView, LoginRequiredMixin, HtmxMixin, TemplateView):
    template_name = "workspace_views/my_workspaces_view.html"

    def get_module_id(self) -> str | None:
        return None

    def get_sub_module_id(self) -> str | None:
        return None

    def get_workspace(self) -> Workspace | None:
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "workspaces": [self.build_workspace_item(item) for item in self.get_visible_workspaces()],
                "create_url": reverse(get_create_view_url(Workspace, "relative")),
            }
        )
        return context
