from functools import cached_property
from typing import Any

from django.views.generic.detail import DetailView
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import ObjectHTMLAction, get_model_config
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.model_context_mixin import BloomerpModelContextMixin
from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from bloomerp.models.users.user_detail_view_tabs_preference import (
    UserDetailViewTabsPreference,
)
from bloomerp.services.preference_services import PreferenceManager


class BaseBloomerpDetailView(BaseBloomerpView, BloomerpModelContextMixin, DetailView):
    htmx_template = "views/htmx_base.html"
    tabs = None
    exclude_header = False
    permissions : list[str] = ["view"]
    permission_fields : list[tuple[str, str]] = []
    htmx_include_addendum_padding = False
    
    @cached_property
    def detail_tabs_preference(self) -> UserDetailViewTabsPreference:
        """Resolve the selected tab layout independently from the field layout."""
        content_type = ContentType.objects.get_for_model(self.model)
        return PreferenceManager(self.request.user).get_or_create_selected(
            UserDetailViewTabsPreference,
            scope={"content_type_id": content_type.pk},
        )
    
    def _can_change_avatar(self, content_type: ContentType) -> bool:
        """Whether the user can change the avatar field

        Args:
            content_type (ContentType): the content type

        Returns:
            bool: response
        """
        obj = self.get_object()
        try:
            obj._meta.get_field("avatar")
        except FieldDoesNotExist:
            return False

        avatar_field = ApplicationField.objects.filter(
            content_type=content_type,
            field="avatar",
        ).first()
        if not avatar_field:
            return False

        permission_manager = UserPermissionManager(self.request.user)
        permission_str = create_permission_str(obj, "change")
        return (
            permission_manager.has_access_to_object(obj, permission_str)
            and permission_manager.has_field_permission(avatar_field, permission_str)
        )

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
            
        content_type = ContentType.objects.get_for_model(self.model)
        context["detail_view_content_type_id"] = content_type.pk
        context["detail_sidebar_view"] = self.request.user.detail_sidebar_view_preference
        context["can_change_avatar"] = self._can_change_avatar(content_type)
        tabs_preference = self.detail_tabs_preference
        preference_manager = PreferenceManager(self.request.user)
        context["detail_tabs_preference"] = tabs_preference
        context["can_manage_detail_tabs_preference"] = preference_manager.can_manage(
            tabs_preference
        )
        context["tab_items"] = tabs_preference.build_rendered_items(
            object_pk=self.object.pk,
            request_path=self.request.path,
        )
        context["tabs"] = [
            item for item in context["tab_items"] if not item["is_folder"]
        ]
        context["object_actions"] = self.get_object_actions()
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
                        "name" : route.localized_name,
                        "url" : route.url_name,
                        "path" : route.path,
                        "requires_pk" : True
                    }
                )
        return tabs
    

    def get_object_actions(self):
        config = get_model_config(self.model)
        if config and config.object_actions:
            return config.object_actions

        return []
    
    
    

        
