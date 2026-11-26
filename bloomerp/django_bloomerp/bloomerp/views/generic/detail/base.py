import time
from functools import cached_property
from typing import Any
from urllib.parse import unquote, urlsplit

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db.models import F, Window
from django.db.models.functions import FirstValue, Lag, Lead
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.views.generic.detail import DetailView

from bloomerp.models.actions.object.resolution import (
    get_object_actions,
    iter_object_actions,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    DetailTabsConfiguration,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    ObjectActionGrouping,
)
from bloomerp.models.users.user_detail_view_tabs_preference import (
    UserDetailViewTabsPreference,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager, create_permission_str
from bloomerp.router import router
from bloomerp.services.action_services import action_is_visible
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tokens import (
    DetailViewToken,
    get_detail_token,
    request_token_headers,
)
from bloomerp.utils.models import get_detail_view_url
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.model_context_mixin import BloomerpModelContextMixin

# Note: we'd wanna make sure all the detail views adhere to the permission checks

class BaseBloomerpDetailView(BaseBloomerpView, BloomerpModelContextMixin, DetailView):
    htmx_template = "views/htmx_base.html"
    tabs = None
    exclude_header = False
    permissions : list[str] = ["view"]
    permission_fields : list[tuple[str, str]] = []
    htmx_include_addendum_padding = False

    @cached_property
    def detail_view_token(self) -> DetailViewToken | None:
        """Verify the detail presentation token for the current viewer and model."""
        return get_detail_token(self.request, self.model)
    
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

        permission_manager = UserPolicyManager(self.request.user)
        return (
            permission_manager.has_access_to_object(obj, BloomerpPermission.CHANGE)
            and permission_manager.has_field_permission(avatar_field, BloomerpPermission.CHANGE)
        )

    def has_permission(self) -> bool:
        """
        Overrides the permission required mixin and checks
        whether the user has certain permissions.
        """
        if self.request.user.is_superuser:
            return True

        manager = UserPolicyManager(self.request.user)
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

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Build the detail header, tabs, object navigation, and sidebar context."""
        context_id = self.get_request_context_id()
        context = super().get_context_data(**kwargs)
        if context_id is not None:
            context["detail_request_context_id"] = context_id
            context["request_context_headers"] = request_token_headers(context_id)
        context["exclude_header"] = self.exclude_header
        if self.tabs:
            context["tabs"] = self.tabs
            
        content_type = ContentType.objects.get_for_model(self.model)
        context["detail_view_content_type_id"] = content_type.pk
        if "pk" in self.kwargs and not context.get("embedded_detail_view"):
            context["object_navigation"] = self._object_navigation_urls()
        actions = self.get_object_actions()
        context["object_actions"] = actions
        context["detail_sidebar_url"], context["highlight_comment_id"] = self._sidebar_initial_state(
            actions, content_type,
        )
        context["can_change_avatar"] = self._can_change_avatar(content_type)
        token = self.detail_view_token
        if token is not None and token.tab_configuration is not None:
            context["detail_tabs_preference"] = None
            context["can_manage_detail_tabs_preference"] = False
            context["tab_items"] = self._configured_tab_items(token.tab_configuration)
        else:
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
        return context

    def _configured_tab_items(self, configuration: DetailTabsConfiguration) -> list[dict[str, Any]]:
        """Render signed tabs and preserve the request tokens on same-model detail links."""
        items = UserDetailViewTabsPreference.build_configured_rendered_items(
            configuration, model=self.model, object_pk=self.object.pk, request_path=self.request.path,
        )
        for item in items:
            tabs = item["tabs"] if item["is_folder"] else (item,)
            for tab in tabs:
                url = tab["href"]
                if self._is_same_model_detail_link(url):
                    tab["href"] = url
        return items

    def _is_same_model_detail_link(self, url: str) -> bool:
        """Check that a link stays on this site and resolves to this model's detail view."""
        if not url.startswith("/") or url.startswith("//") or "\\" in url:
            return False
        try:
            view = resolve(unquote(urlsplit(url).path)).func
        except Resolver404:
            return False
        view_class = getattr(view, "view_class", None)
        return (
            view_class is not None
            and issubclass(view_class, BaseBloomerpDetailView)
            and view.view_initkwargs.get("model", view_class.model) is self.model
        )

    def _object_navigation_urls(self) -> tuple[str, str] | None:
        """Return links to adjacent visible objects in the model's default order."""
        manager = UserPolicyManager(self.request.user)
        if not manager.has_global_permission(self.model, BloomerpPermission.VIEW):
            return None
        visible = manager.get_accessible_queryset(self.model, BloomerpPermission.VIEW)
        ordering = [field for field in self.model._meta.ordering if field != "?"] + ["pk"]
        neighbors = (
            self.get_queryset()
            .filter(pk__in=visible.order_by().values("pk"))
            # Filter by a window alias so the neighboring rows remain in the window.
            .alias(navigation_pk=Window(FirstValue("pk"), partition_by=F("pk")))
            .filter(navigation_pk=self.object.pk)
            .annotate(
                previous_pk=Window(Lag("pk"), order_by=ordering),
                next_pk=Window(Lead("pk"), order_by=ordering),
            )
            .values_list("previous_pk", "next_pk")
            .first()
        )
        if neighbors is None:
            return None

        route = get_detail_view_url(self.model)
        previous_pk, next_pk = neighbors
        try:
            previous_url = reverse(route, kwargs={"pk": previous_pk}) if previous_pk is not None else ""
            next_url = reverse(route, kwargs={"pk": next_pk}) if next_pk is not None else ""
        except NoReverseMatch:
            return None
        return (
            previous_url or "",
            next_url or "",
        )

    def _sidebar_initial_state(
        self,
        actions: list[ObjectActionDefinition],
        content_type: ContentType,
    ) -> tuple[str, str]:
        """Use enabled sidebar actions to resolve the initial URL and any comment deep link."""
        action_context = ObjectActionContext(
            request=self.request, model=self.model, content_type=content_type,
            object=self.object, surface="detail",
        )

        def group_is_visible(group: ObjectActionGrouping) -> bool:
            """Check group visibility in the same detail context as its actions."""
            return action_is_visible(group, action_context)

        sidebar_actions = {
            action.id: action
            for action in iter_object_actions(actions, include_group=group_is_visible)
            if isinstance(action, ObjectAction) and action.id in {"activity", "comments"}
            and action.endpoint and action_is_visible(action, action_context)
        }
        preferences = (
            self.request.GET.get("sidebar"), self.request.user.detail_sidebar_view_preference,
            "activity", "comments",
        )
        for name in preferences:
            action = sidebar_actions.get(name)
            if action is None:
                continue
            endpoint = action.endpoint
            url = endpoint(action_context) if callable(endpoint) else endpoint
            if not url:
                continue
            comment_id = self.request.GET.get("comment", "")
            if name == "comments" and comment_id.isascii() and comment_id.isdecimal():
                separator = "&" if "?" in url else "?"
                return f"{url}{separator}highlight={comment_id}", comment_id
            return url, ""
        return "", ""

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
    

    def get_object_actions(self) -> list[ObjectActionDefinition]:
        """Return the model's built-in and configured detail actions."""
        return get_object_actions(self.model, surface="detail")
    
    
    

        
