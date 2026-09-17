from django.contrib.contenttypes.models import ContentType

from .base import BaseBloomerpDetailView
from bloomerp.models.files import File
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
class BloomerpDetailFileListView(BaseBloomerpDetailView):
    template_name = "views/generic/detail/files.html"
    modules = None
    permission_fields = [("files", "view")]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ensure_folder_hierarchy_for_object(
            self.object,
            created_by=self.request.user,
            updated_by=self.request.user,
        )
        context["file_content_type_id"] = ContentType.objects.get_for_model(File).pk
        context["filters"] = {
            "content_type": ContentType.objects.get_for_model(
                self.get_object()._meta.model
            ).id,
            "object_id": self.get_object().id,
        }
        return context
