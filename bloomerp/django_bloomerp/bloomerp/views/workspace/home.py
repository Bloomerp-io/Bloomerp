from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from bloomerp.views.mixins.conditional_staff_required_mixin import ConditionalStaffRequiredMixin
from bloomerp.views.mixins.htmx_mixin import HtmxMixin
from bloomerp.router import router
from bloomerp.modules.definition import module_registry
from bloomerp.utils.realtime import send_user_message

@router.register(
    path="/",
    name='Modules',
    description='Available Modules',
    route_type='app',
    url_name='bloomerp_home_view'
)
class BloomerpHomeView(HtmxMixin, LoginRequiredMixin, ConditionalStaffRequiredMixin, TemplateView):
    template_name = 'workspace_views/bloomerp_home_view.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modules"] = module_registry.get_root_modules()
        #send_user_message(1, {"type": "toast", "message": "Hello from Channels", "level": "success"})
        return context



        


    
