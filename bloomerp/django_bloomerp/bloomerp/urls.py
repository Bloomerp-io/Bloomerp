from django.urls import include, path,  register_converter
from django.urls import NoReverseMatch
from django.contrib.auth import views as auth_views
from django.contrib.contenttypes.models import ContentType
from rest_framework.response import Response
from rest_framework.reverse import reverse
from bloomerp.config.definition import BloomerpConfig
from bloomerp.models.access_control.policy import Policy
from bloomerp.views.api.access_control import PolicyViewSet
from django.db.models import Model
from bloomerp.utils.models import (model_name_plural_underline)
from bloomerp.utils.api import generate_serializer, generate_model_viewset_class
from bloomerp.views.api_views import BloomerpModelViewSet
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.utils.urls import IntOrUUIDConverter
from rest_framework.routers import DefaultRouter
from bloomerp.router import router
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.urls import reverse_lazy
from django.conf import settings

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

# Get the config
bloomerp_config : BloomerpConfig = getattr(settings, "BLOOMERP_CONFIG", None)

# Get the base URL from the settings
urlpatterns = [
    # login URL
    path('login/', auth_views.LoginView.as_view(
            template_name='auth_views/login_view.html',
            next_page=reverse_lazy('bloomerp_home_view')
            ), name='login'),
    path('logout/',auth_views.LogoutView.as_view(next_page=reverse_lazy('login')), name='logout'),
]

# Get the content types
try:
    content_types = list(ContentType.objects.all())
except Exception:
    # Database might not be ready yet (e.g., during initial migrations)
    content_types = []

# Loop through all the content types
for content_type in content_types:
    if content_type.model_class():
        model : Model = content_type.model_class()
        
        if not model:
            continue

        if model is Policy:
            continue
        
        try:
            admin.site.register(model)
        except AlreadyRegistered:
            pass

        serializer_class = generate_serializer(model)
        ApiViewSet = generate_model_viewset_class(
            model=model,
            serializer=serializer_class,
            base_viewset=BloomerpModelViewSet
        )

        try:
            config = getattr(model, "bloomerp_config", None)
            if isinstance(config, BloomerpModelConfig):
                if not config.should_enable_api_auto_generation():
                    continue
                
            drf_router.register(
                prefix = model_name_plural_underline(model), 
                viewset = ApiViewSet, 
                basename=model_name_plural_underline(model)
            )
            
        except Exception as e:
            # Don't fail URL loading if a single model registration errors
            pass

# Register models
drf_router.register(
    prefix = model_name_plural_underline(Policy),
    viewset = PolicyViewSet,
    basename=model_name_plural_underline(Policy)
)

# Add api's to url patterns
urlpatterns += [
    path('api/', include(drf_router.urls)),
]

# Create url patterns
urlpatterns.extend(router.create_url_patterns())
