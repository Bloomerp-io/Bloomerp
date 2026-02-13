# ---------------------------------
# The URL patterns for the BloomerpEngine
# This file is responsible for generating the URL patterns for the BloomerpEngine
# ---------------------------------
from django.urls import include, path,  register_converter
from django.contrib.auth import views as auth_views
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.access_control.policy import Policy
from bloomerp.views.api.access_control import PolicyViewSet
from django.db.models import Model
from bloomerp.utils.models import (model_name_plural_underline)
from bloomerp.utils.api import generate_serializer, generate_model_viewset_class
from bloomerp.views.api_views import BloomerpModelViewSet
from bloomerp.utils.urls import IntOrUUIDConverter
from rest_framework.routers import DefaultRouter
from bloomerp.router import router
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered


# Register the custom URL converter
register_converter(IntOrUUIDConverter, 'int_or_uuid') # Register the custom URL converter
drf_router = DefaultRouter()

# Get the base URL from the settings
from django.conf import settings
BASE_URL = settings.BLOOMERP_SETTINGS.get('BASE_URL', '')

# ---------------------------------
# START GENERATION OF URL PATTERNS
#
#           ___/\___
#          |        |
#         /|  O  O  |\      ankers away!
#        / |   ||   | \
#       /  |  ----  |  \
#      |   |  ||||  |   |
#      |  /|  ||||  |\  |
#      \/  |________|  \/
#           |      |
#           |______|
#           |  ||  |
#           |  ||  |
#          /|  ||  |\
#         / |______| \
#         |__________|
#
#           *   *   *
#          *  * * *  *
#         *  *  *  *  *
#        *  *   *   *  *
#       *  *    *    *  *
# ---------------------------------



# ---------------------------------
# Auth related URL patterns
# ---------------------------------
from django.conf import settings


from django.urls import reverse_lazy
urlpatterns = [
    # login URL
    path('login/', auth_views.LoginView.as_view(
            template_name='auth_views/login_view.html',
            next_page=reverse_lazy('bloomerp_home_view')
            ), name='login'),
    path('logout/',auth_views.LogoutView.as_view(next_page=reverse_lazy('login')), name='logout'),
]


# ---------------------------------
# API URL patterns / Admin pannel
# ---------------------------------
try:
    content_types = list(ContentType.objects.all())
except Exception:
    # Database might not be ready yet (e.g., during initial migrations)
    content_types = []

for content_type in content_types:
    if content_type.model_class():
        model : Model = content_type.model_class()
        
        if not model:
            continue
        
        # ---------------------------------
        # Add the model to the admin dashboard
        # ---------------------------------
        
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
            # Only skip API creation for models that explicitly opt-out by
            # setting `skip_api_creation = True` on the model class.
            if getattr(model, 'skip_api_creation', False):
                # explicit opt-out; don't register this model on the API
                continue

            drf_router.register(
                prefix = model_name_plural_underline(model), 
                viewset = ApiViewSet, 
                basename=model_name_plural_underline(model)
            )
            
        except Exception as e:
            # Don't fail URL loading if a single model registration errors
            pass


drf_router.register(
    prefix = model_name_plural_underline(Policy),
    viewset = PolicyViewSet,
    basename=model_name_plural_underline(Policy)
)

urlpatterns += [
    path('api/', include(drf_router.urls)),
]

urlpatterns.extend(router.create_url_patterns())


# ---------------------------------
# Create path
# ---------------------------------
BLOOMERP_URLPATTERNS = path(BASE_URL, include(urlpatterns))
