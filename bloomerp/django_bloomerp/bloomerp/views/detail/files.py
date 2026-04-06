
from bloomerp.models.files import File
from django.urls import reverse
from .base_detail import BloomerpBaseDetailView
from bloomerp.router import router
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object

@router.register(
    path="files",
    name="Files",
    url_name="files",
    description="Files for object for {model} model",
    route_type="detail",
    exclude_models=[File],
)
class BloomerpDetailFileListView(BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_files_view.html"
    modules = None
    permission_fields = [("files", "view")]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        folder = ensure_folder_hierarchy_for_object(
            self.object,
            created_by=self.request.user,
            updated_by=self.request.user,
        )
        params = self.request.GET.copy()
        params["folder_id"] = params.get("folder_id") or str(folder.id)
        params["hide_ancestor_folders"] = "true"
        context["folder"] = folder
        context["file_browser_url"] = f"{reverse('components_files')}?{params.urlencode()}"
        return context

    

    
