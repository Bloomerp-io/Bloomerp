from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from bloomerp.forms.core import BloomerpDownloadBulkUploadTemplateForm
from bloomerp.models.files import File
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
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
    module = None
    
    def has_permission(self):
        manager = UserPermissionManager(self.request.user)
        return manager.has_global_permission(
            self.model,
            create_permission_str("bulk_add")
        )

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.verbose_name
        context["model"] = self.model
        context["title"] = f"Bulk upload {self.model._meta.verbose_name_plural}"
        context["model_name_plural"] = self.model._meta.verbose_name_plural
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).pk
        
        context["fields_form"] = BloomerpDownloadBulkUploadTemplateForm(self.model)
        return context

    