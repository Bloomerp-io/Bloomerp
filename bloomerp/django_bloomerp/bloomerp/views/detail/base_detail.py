from typing import Any
from django.views.generic.detail import DetailView
from bloomerp.models.application_field import ApplicationField
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.mixins import BloomerpModelContextMixin, HtmxMixin
from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.services.detail_view_services import resolve_tabs_with_state
from django.contrib.auth.mixins import PermissionRequiredMixin

class BloomerpBaseDetailView(HtmxMixin, PermissionRequiredMixin, BloomerpModelContextMixin, DetailView):
    htmx_template = "bloomerp_htmx_base_view.html"
    tabs = None
    exclude_header = False
    permissions : list[str] = ["view"]
    permission_fields : list[tuple[str, str]] = []

    def has_permission(self) -> bool:
        """
        Overrides the permission required mixin and checks
        whether the user has certain permissions.
        """
        if self.request.user.is_superuser:
            return True

        manager = UserPermissionManager(self.request.user)
        obj = self.get_object()
        content_type = ContentType.objects.get_for_model(self.model)
        
        for permission in self.permissions:
            if not manager.has_access_to_object(
                obj,
                create_permission_str(obj, permission)
                ):
                return False
        
        if self.permission_fields:
            application_fields = ApplicationField.objects.filter(
                field__in=[entry[0] for entry in self.permission_fields],
                content_type=content_type
            )

            for field_name, permission in self.permission_fields:
                application_field = application_fields.filter(field=field_name).first()
                perm_string = create_permission_str(obj, permission)

                if not manager.has_field_permission(application_field, perm_string):
                    return False

        return True

    def get_context_data(self, **kwargs: Any) -> dict:
        context = super().get_context_data(**kwargs)
        context["exclude_header"] = self.exclude_header
        if self.tabs:
            context["tabs"] = self.tabs
            
        tabs = context.get("tabs") or self.get_tabs()

        content_type = ContentType.objects.get_for_model(self.model)
        context["detail_view_content_type_id"] = content_type.pk
        preference = UserDetailViewPreference.get_or_create_for_user(self.request.user, content_type)
        resolved_tabs, normalized_state = resolve_tabs_with_state(tabs=tabs, state=preference.tab_state_obj)
        if normalized_state != preference.tab_state_obj:
            preference.tab_state = normalized_state
            preference.save(update_fields=["tab_state"])

        context["tabs_top_level"] = resolved_tabs.get("top_level_tabs", [])
        context["tab_folders"] = resolved_tabs.get("folders", [])
        context["tabs"] = resolved_tabs.get("top_level_tabs", [])
        return context

    def get_tabs(self):
        tabs = []
        for route in router.filter(
            model=self.model,
            route_type="detail",
        ):
            if route.nr_of_args() == 1:
                tabs.append(
                    {
                        "key" : route.url_name,
                        "name" : route.name,
                        "url" : route.url_name,
                        "path" : route.path,
                        "requires_pk" : True
                    }
                )
        return tabs
    
    
        