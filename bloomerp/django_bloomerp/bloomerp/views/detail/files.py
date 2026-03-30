
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.files import File
from .base_detail import BloomerpBaseDetailView
from bloomerp.router import router

@router.register(
    path="files",
    name="Files",
    url_name="files",
    description="Files for object for {model} model",
    route_type="detail",
    exclude_models=[File],
)
class BloomerpDetailFileListView(BloomerpBaseDetailView):
    template_name = "snippets/files_snippet.html"
    modules = None
    permission_fields = [("files", "view")]

