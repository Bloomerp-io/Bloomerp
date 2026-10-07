from typing import Any

from django.db.models import Model
from django.views.generic import TemplateView

from bloomerp.models.files import File
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.model_context_mixin import BloomerpModelContextMixin


@router.register(
    path="/",
    name="{model} List",
    url_name="model",
    description="List of records for {model} model",
    route_type="model",
    exclude_models=[File],
)
class BloomerpListView(BaseBloomerpView, BloomerpModelContextMixin, TemplateView):
    model: Model = None
    module = None
    template_name: str = "views/generic/model/bloomerp_list.html"
    context_object_name: str = "object_list"
    create_object_url: str = None
    permission_required = None

    def has_permission(self):
        return UserPolicyManager(self.request.user).has_global_permission(
            self.model,
            BloomerpPermission.VIEW
        )

    def get_context_data(self, **kwargs: Any) -> dict:
        """Use the model's plural name for this list page's visible labels."""
        context = super().get_context_data(**kwargs)
        title = self.model._meta.verbose_name_plural.capitalize()
        context["title"] = title
        context["route_title"] = title
        breadcrumbs = context.get("breadcrumbs", [])
        if breadcrumbs and breadcrumbs[-1].get("active"):
            breadcrumbs[-1]["text"] = title
        return context
