from django.shortcuts import render
from django.views.generic import View
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.files import File
from bloomerp.views.mixins import HtmxMixin
from registries.route_registry import router


@router.register(
    path="list",
    name="Files",
    url_name="list",
    description="Bloomerp Files",
    route_type="list",
    models=[File],
)
class BloomerpFileListView(PermissionRequiredMixin, HtmxMixin, View):
    template_name = "list_views/bloomerp_file_list_view.html"
    model = File

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
        context["target"] = "file_list"
        context["application_fields"] = ApplicationField.objects.filter(
            content_type=ContentType.objects.get_for_model(self.model),
            field__in=fields,
        )
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).id
        return context

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()

        return render(request, self.template_name, context)
