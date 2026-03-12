from bloomerp.router import router
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.services.sectioned_layout_services import dump_layout_json
from bloomerp.views.mixins import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


@router.register(
    path=f"/",
    name='{module}',
    description='The homepage for the {module} module.',
    route_type='module',
    modules="__all__"
)
class BloomerpModuleHomeView(HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_module_home_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["module"] = self.module
        module_id = getattr(self.module, "id", "") if self.module else ""
        workspace = Workspace.get_or_create_for_user(self.request.user, module_id=module_id)
        context["workspace"] = workspace
        context["workspace_layout_json"] = dump_layout_json(workspace.layout_obj)
        return context
