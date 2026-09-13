from django.views.generic import TemplateView

from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.modules.definition import module_registry
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.views.workspaces.base import BaseWorkspaceView


@router.register(
    path="/",
    name='Modules',
    description='Available Modules',
    route_type='app',
    url_name='bloomerp_home_view'
)
class BloomerpHomeView(BaseWorkspaceView, TemplateView):
    template_name = "views/workspaces/bloomerp_home_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = self.get_workspace()

        if workspace:
            context.update(self.get_workspace_template_context())
            context["show_module_selector"] = True
        else:
            accessible_models = UserPolicyManager(self.request.user).get_accessible_models(
                BloomerpPermission.VIEW
            )
            all_modules = module_registry.get_root_modules()
            accessible_modules = [
                module for module in all_modules if any(
                    model in accessible_models for model in module_registry.get_models_for_module(module.id, include_descendants=True)
                )
            ]
            context["modules"] = accessible_modules
        return context

    def get_module_id(self) -> None:
        """Return the unscoped module id used by general workspaces."""
        return None

    def get_workspace(self) -> Workspace | None:
        """Return the selected general workspace unless modules were requested."""
        if self.request.GET.get("modules") == "1":
            return None

        return PreferenceManager(self.request.user).get_or_create_selected(
            Workspace,
            {"module_id": None},
            force_create=False,
        )
