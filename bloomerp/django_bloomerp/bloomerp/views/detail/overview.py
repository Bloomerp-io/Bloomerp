from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.services.detail_view_services import create_default_detail_view_preference
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.views.core import BloomerpBaseDetailView
from registries.route_registry import router
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from typing import Any
from bloomerp.models import ApplicationField

@router.register(
    path="",
    name="Overview",
    url_name="overview",
    description="Overview of object from {model} model",
    route_type="detail",
    models = "__all__",
)
class BloomerpDetailOverviewView(PermissionRequiredMixin, BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_overview_view.html"
    settings = None

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.view_{self.model._meta.model_name}"]

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        content_type = ContentType.objects.get_for_model(self.model)
    
        # Get the detail view preference
        preference = self._get_or_create_detail_view_preference(content_type, self.request.user)

        # Add content type id to context
        layout = self.resolve_layout(preference, content_type)
        context["content_type_id"] = content_type.pk
        context["layout"] = layout
        return context

    def _get_or_create_detail_view_preference(self, content_type, user) -> UserDetailViewPreference:
        qs = UserDetailViewPreference.objects.filter(
           content_type=content_type,
           user=user,
        )
        if qs.exists():
            return qs.first()
        return create_default_detail_view_preference(content_type, user)
    
    
    def resolve_layout(self, preference:UserDetailViewPreference, content_type:ContentType) -> dict:
        """_summary_

        Args:
            preference (UserDetailViewPreference): _description_
            content_type (ContentType): _description_

        Returns:
            dict: _description_
        """
        manager = UserPermissionManager(self.request.user)
        permission_str = f"view_{self.model._meta.model_name}"

        layout: dict = {}
        sections: list = []

        for section in getattr(preference.field_layout_obj, "sections", []):
            _section = {
                "columns": getattr(section, "columns", None),
                "title": getattr(section, "title", None),
            }
            
            items: list = []
            for item in getattr(section, "items", []) or []:
                try:
                    field = ApplicationField.objects.filter(id=item, content_type=content_type).first()
                except Exception:
                    field = None

                if not field:
                    continue

                # Check permission on the actual ApplicationField
                can_view = manager.has_field_permission(field, permission_str)
                if not can_view:
                    continue
                items.append(
                    {
                        "application_field" : field,
                        "can_view": can_view,
                        "can_edit": manager.has_field_permission(field, f"change_{self.model._meta.model_name}"),
                    }
                )

            _section["items"] = items
            sections.append(_section)

        layout["sections"] = sections
        return layout
    