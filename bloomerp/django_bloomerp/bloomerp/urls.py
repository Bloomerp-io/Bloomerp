# ---------------------------------
# The URL patterns for the BloomerpEngine
# This file is responsible for generating the URL patterns for the BloomerpEngine
# ---------------------------------
from django.urls import include, path,  register_converter
from django.contrib.auth import views as auth_views
from django.contrib.contenttypes.models import ContentType
from zmq import has
from bloomerp.models.access_control.policy import Policy
from bloomerp.views.api.access_control import PolicyViewSet
from bloomerp.views.document_templates import router as document_template_router
from django.db.models import Model
from bloomerp.utils.models import ( 
    model_name_plural_underline, 
    get_base_model_route,
    )
from bloomerp.utils.api import generate_serializer, generate_model_viewset_class
from bloomerp.views.api_views import BloomerpModelViewSet
from bloomerp.utils.urls import IntOrUUIDConverter
from rest_framework.routers import DefaultRouter
from bloomerp.router import router

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
            
        serializer_class = generate_serializer(model)
        
        ApiViewSet = generate_model_viewset_class(
            model=model,
            serializer=serializer_class,
            base_viewset=BloomerpModelViewSet
        )

        try:
            if hasattr(model, 'skip_api_creation') and not model.skip_api_creation:
                
                drf_router.register(
                    prefix = model_name_plural_underline(model), 
                    viewset = ApiViewSet, 
                    basename=model_name_plural_underline(model)
                    )
        except:
            pass

        # ---------------------------------
        # Add the model to the admin dashboard
        # ---------------------------------
        from django.contrib import admin
        from django.contrib.admin.sites import AlreadyRegistered
        try:
            admin.site.register(model)
        except AlreadyRegistered:
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
