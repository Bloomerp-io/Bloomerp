from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from bloomerp.forms.core import BloomerpDownloadBulkUploadTemplateForm
from bloomerp.models.files import File
from bloomerp.utils.models import model_name_plural_underline
from bloomerp.views.mixins import HtmxMixin
from bloomerp.router import router


@router.register(
    path="bulk-upload",
    name="Bulk Upload {model}",
    url_name="bulk_upload",
    description="Bulk upload objects from {model}",
    route_type="model",
    exclude_models=[File],
)
class BloomerpBulkUploadView(PermissionRequiredMixin, HtmxMixin, View):
    template_name = "list_views/bloomerp_bulk_upload_view.html"
    model = None
    success_url = None
    success_message = "Objects were uploaded successfully."

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.bulk_add_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.verbose_name
        context["model"] = self.model
        context["title"] = f"Bulk upload {self.model._meta.verbose_name_plural}"
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        context["list_view_url"] = model_name_plural_underline(self.model) + "_list"
        context["fields_form"] = BloomerpDownloadBulkUploadTemplateForm(self.model)
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        return render(request, self.template_name, context)
