from typing import Any

from django.views.generic import TemplateView

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.views.workspaces.base import BaseWorkspaceView


@router.register(
    path="/",
    name="Modules",
    description="Available Modules",
    route_type="app",
    url_name="bloomerp_home_view",
)
class BloomerpHomeView(BaseWorkspaceView, TemplateView):
    template_name = "views/workspaces/bloomerp_home_view.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Render the selected workspace or the shared permission-scoped root modules."""
        context = super().get_context_data(**kwargs)
        workspace = self.get_workspace()

        if workspace:
            context.update(self.get_workspace_template_context())
            context["show_module_selector"] = True
        else:
            context["modules"] = [
                module
                for module in UserPolicyManager(
                    self.request.user
                ).get_accessible_modules(BloomerpPermission.VIEW)
                if module.parent_module_id is None
            ]
        return context

    def get_module_id(self) -> None:
        """Return the unscoped module id used by general workspaces."""
        return

    def get_workspace(self) -> Workspace | None:
        """Return the selected general workspace unless modules were requested."""
        if self.request.GET.get("modules") == "1":
            return None

        return PreferenceManager(self.request.user).get_or_create_selected(
            Workspace,
            {"module_id": None},
            force_create=False,
        )
