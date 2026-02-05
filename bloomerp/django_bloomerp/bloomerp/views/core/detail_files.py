from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.application_field import ApplicationField
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
class BloomerpDetailFileListView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name = "snippets/files_snippet.html"

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fields = [
            "name",
            "datetime_created",
            "datetime_updated",
            "created_by",
            "updated_by",
            "object_id",
            "content_type",
        ]

        context["files_application_fields"] = ApplicationField.objects.filter(
            content_type=ContentType.objects.get_for_model(File),
            field__in=fields,
        )
        context["title"] = f"Files for {self.get_object()}"
        context["target"] = "file_results"
        return context
