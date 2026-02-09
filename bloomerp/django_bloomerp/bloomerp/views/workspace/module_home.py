from bloomerp.router import router
from bloomerp.views.mixins import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


@router.register(
    path=f"/",
    name='{module} home',
    description='The homepage for the {module} module.',
    route_type='module',
    modules="__all__"
)
class BloomerpModuleHomeView(HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_module_home_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["module"] = self.module
        return context