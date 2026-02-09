from typing import Any
from django.db.models import Model
from django.views.generic.list import ListView
from django.contrib.auth.mixins import PermissionRequiredMixin
from bloomerp.models.files import File
from bloomerp.views.mixins import BloomerpModelContextMixin, HtmxMixin
from bloomerp.router import router


@router.register(
    path="/",
    name="{model} list",
    url_name="model",
    description="List of {model} model",
    route_type="model",
    exclude_models=[File],
)
class BloomerpListView(PermissionRequiredMixin, BloomerpModelContextMixin, HtmxMixin, ListView):
    model: Model = None
    module = None
    template_name: str = "list_views/bloomerp_list_view.html"
    context_object_name: str = "object_list"
    create_object_url: str = None
    permission_required = None

    def get_permission_required(self):
        if self.permission_required:
            return self.permission_required
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def has_permission(self):
        return True

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["title"] = self.model._meta.verbose_name.capitalize() + " list"
        return context
