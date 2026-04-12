from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.files import File
from bloomerp.views.mixins import HtmxMixin
from bloomerp.router import router


@router.register(
    path="files",
    route_type="app",
    name="Files",
    url_name="app",
    description="List of all files across the application.",
)
class BloomerpFileListView(PermissionRequiredMixin, HtmxMixin, TemplateView):
    template_name = "list_views/bloomerp_file_list_view.html"
    model = File
    module = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query_string = self.request.GET.urlencode()
        context["file_browser_url"] = reverse("components_files")
        if query_string:
            context["file_browser_url"] = f"{context['file_browser_url']}?{query_string}"
        return context
    
    def has_permission(self):
        return True
