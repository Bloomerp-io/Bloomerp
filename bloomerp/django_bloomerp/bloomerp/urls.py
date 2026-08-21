import logging

from django.apps import apps
from django.contrib.auth import views as auth_views
from django.views.i18n import JSONCatalog
from django.urls import include, path,  register_converter
from django.urls import NoReverseMatch
from rest_framework.response import Response
from rest_framework.reverse import reverse
from bloomerp.config.definition import BloomerpConfig
from bloomerp.serializers.model_serializers import set_serializer_cls
from django.db.models import Model
from bloomerp.utils.models import (model_name_plural_underline)
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.urls import IntOrUUIDConverter
from rest_framework.routers import DefaultRouter
from bloomerp.router import router
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.urls import reverse_lazy
from django.conf import settings
from bloomerp.auth import allauth_is_enabled
from bloomerp.views.auth.login import BloomerpLoginView

logger = logging.getLogger(__name__)


class PublicApiRootRouter(DefaultRouter):
    def _should_include_api_root_entry(self, request, viewset) -> bool:
        model = getattr(viewset, "model", None)
        if model is None:
            return bool(getattr(request, "user", None) and request.user.is_authenticated)

        config = getattr(model, "bloomerp_config", None)
        if isinstance(config, BloomerpModelConfig) and config.has_public_access():
            return True

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        permission_manager = UserPermissionManager(user)
        permission_str = create_permission_str(model, "view")
        return (
            permission_manager.has_global_permission(model, permission_str)
            or permission_manager.has_row_level_access(model, permission_str)
        )

    def get_api_root_view(self, api_urls=None):
        router = self

        class APIRoot(self.APIRootView):
            def get(inner_self, request, *args, **kwargs):
                ret = {}
                namespace = inner_self.request.resolver_match.namespace
                for prefix, viewset, basename in router.registry:
                    if not router._should_include_api_root_entry(request, viewset):
                        continue

                    key = prefix
                    url_name = f"{basename}-list"
                    if namespace:
                        url_name = namespace + ":" + url_name
                    try:
                        ret[key] = reverse(
                            url_name,
                            args=args,
                            kwargs=kwargs,
                            request=request,
                            format=kwargs.get("format"),
                        )
                    except NoReverseMatch:
                        continue
                return Response(ret)

        return APIRoot.as_view()

# Register the custom URL converter
register_converter(IntOrUUIDConverter, 'int_or_uuid') # Register the custom URL converter
drf_router = PublicApiRootRouter()


def get_api_models() -> list[type[Model]]:
    api_models: list[type[Model]] = []

    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        
        set_serializer_cls(model)
        api_models.append(model)

    return api_models


def register_model_with_admin(model: type[Model]) -> None:
    try:
        admin.site.register(model)
    except AlreadyRegistered:
        pass


# Get the config
bloomerp_config : BloomerpConfig = getattr(settings, "BLOOMERP_CONFIG", None)

# Get the login URL
login_url = getattr(settings, "LOGIN_URL", "/login/")

# Derive the logout URL from the login URL if not explicitly set
logout_url = getattr(settings, "LOGOUT_URL", None)
if logout_url is None:
    if login_url.endswith('/login/'):
        logout_url = login_url[:-len('login/')] + 'logout/'
    else:
        logout_url = '/logout/'

if login_url.startswith('/'):
    login_url = login_url[1:]
if logout_url.startswith('/'):
    logout_url = logout_url[1:]

# Get the base URL from the settings
urlpatterns = [
    # login URL
    path(login_url, BloomerpLoginView.as_view(), name='login'),
    path(logout_url, auth_views.LogoutView.as_view(next_page=reverse_lazy('login')), name='logout'),
    path("i18n/", include("django.conf.urls.i18n")),
    path(
        "i18n/catalog.json",
        JSONCatalog.as_view(domain="djangojs"),
        name="bloomerp_javascript_catalog",
    ),
]

if allauth_is_enabled():
    urlpatterns.append(path("accounts/", include("allauth.urls")))
# Create url patterns
urlpatterns.extend(router.create_url_patterns())
