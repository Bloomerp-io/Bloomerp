from typing import Any
from django.db.models import Model
from django.views.generic.list import ListView
from django.contrib.auth.mixins import PermissionRequiredMixin
from bloomerp.models.files import File
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.mixins import BloomerpModelContextMixin, HtmxMixin
from bloomerp.router import router


@router.register(
    path="/",
    name="{model} List",
    url_name="model",
    description="List of records for {model} model",
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

    def has_permission(self):
        return UserPermissionManager(self.request.user).has_global_permission(
            self.model,
            create_permission_str(self.model, "view")
        )

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["title"] = self.model._meta.verbose_name.capitalize() + " list"
        return context
