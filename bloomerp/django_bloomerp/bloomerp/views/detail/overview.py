from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.views.detail.base_detail import BloomerpBaseDetailView
from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from typing import Any
from bloomerp.services.detail_view_services import get_default_layout
from bloomerp.services.sectioned_layout_services import resolve_detail_layout_rows

@router.register(
    path="/",
    name="Details",
    url_name="overview",
    description="Overview of object from {model} model",
    route_type="detail",
    models = "__all__",
)
class BloomerpDetailOverviewView(BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_overview_view.html"
    settings = None


    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        content_type = ContentType.objects.get_for_model(self.model)
    
        preference = self._get_or_create_detail_view_preference(content_type, self.request.user)
        layout = self.resolve_layout(preference, content_type)
        if not any(row.get("items") for row in layout["rows"]):
            preference.field_layout = get_default_layout(content_type=content_type, user=self.request.user).model_dump()
            preference.save(update_fields=["field_layout"])
            layout = self.resolve_layout(preference, content_type)
        context["content_type_id"] = content_type.pk
        context["layout"] = layout
        # TODO: These two attributes can be derived from the type, i.e. they don't need to be passed on actually...
        context["layout_available_items_url"] = f"/components/workspaces/crud_layout_available_fields/?content_type_id={content_type.pk}&layout_kind=detail"
        context["layout_render_item_url"] = "/components/workspaces/crud_layout_render_field/?layout_kind=detail"
        context["detail_object_id"] = self.object.pk
        return context

    def _get_or_create_detail_view_preference(self, content_type, user) -> UserDetailViewPreference:
        return UserDetailViewPreference.get_or_create_for_user(user, content_type)
     
    def resolve_layout(self, preference:UserDetailViewPreference, content_type:ContentType) -> dict:
        return {
            "rows": resolve_detail_layout_rows(
                layout=preference.field_layout_obj,
                content_type=content_type,
                user=self.request.user,
            )
        }
    
