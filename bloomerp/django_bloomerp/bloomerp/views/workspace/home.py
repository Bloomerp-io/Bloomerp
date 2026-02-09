from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from bloomerp.views.mixins import HtmxMixin
from bloomerp.router import router
from bloomerp.modules.definition import module_registry

@router.register(
    path="/",
    name='Bloomerp Dashboard',
    description='The dashboard for the Bloomerp app',
    route_type='app',
    url_name='bloomerp_home_view'
)
class BloomerpHomeView(HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_home_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modules"] = module_registry.get_all().values()
        return context



        


    