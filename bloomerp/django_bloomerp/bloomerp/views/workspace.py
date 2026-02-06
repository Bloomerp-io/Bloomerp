from operator import mod
from django.shortcuts import render
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.workspaces import Widget
from django.views import View
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Model
from bloomerp.views.mixins import HtmxMixin
from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from bloomerp.modules.definition import module_registry

@router.register(
    path="/",
    name='Bloomerp Dashboard',
    description='The dashboard for the Bloomerp app',
    route_type='app',
    url_name='bloomerp_home_view'
)
class BloomerpHomeView(HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_workspace_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modules"] = module_registry.get_all().values()
        return context


for module in module_registry.get_all().values():
    @router.register(
        path=f"/{module.code}/",
        name=f'{module.name} Workspace',
        description=f'The workspace for the {module.name} module',
        route_type='app',
        url_name=f'bloomerp_{module.code}_workspace_view'
    )
    class BloomerpModuleWorkspaceView(HtmxMixin, LoginRequiredMixin, TemplateView):
        template_name = 'workspace_views/bloomerp_workspace_view.html'

        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            print(f"Loading workspace for module: {module.name}")
            return context
    