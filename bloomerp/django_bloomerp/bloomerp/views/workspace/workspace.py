from bloomerp.router import router
from bloomerp.views.mixins import HtmxMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

@router.register(
    path="workspace/",
    name="models",
    route_type="module",
    modules="__all__",
)
class BloomerpModuleHomeView(HtmxMixin, LoginRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_module_home_view.html'
