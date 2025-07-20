# ---------------------------------
# The URL patterns for the BloomerpEngine
# This file is responsible for generating the URL patterns for the BloomerpEngine
# ---------------------------------
from django.urls import include, path,  register_converter
from django.contrib.auth import views as auth_views
from django.contrib.contenttypes.models import ContentType
from bloomerp.components import datatable, todos
from bloomerp.components.document_templates import generate_document_template
from bloomerp.components.llm import llm_executor, ai_conversations
from bloomerp.views.document_templates import router as document_template_router
from django.db.models import Model
from bloomerp.utils.models import ( 
    model_name_plural_underline, 
    get_base_model_route,
    )
from bloomerp.utils.api import generate_serializer, generate_model_viewset_class
from bloomerp.views.api import BloomerpModelViewSet
from bloomerp.utils.urls import IntOrUUIDConverter
from rest_framework.routers import DefaultRouter
from bloomerp.utils.router import _get_routers_from_settings, RouteFinder, BloomerpRouterHandler

# Register the custom URL converter
register_converter(IntOrUUIDConverter, 'int_or_uuid') # Register the custom URL converter
drf_router = DefaultRouter()

# Get the base URL from the settings
from django.conf import settings
BASE_URL = settings.BLOOMERP_SETTINGS.get('BASE_URL', '')

# Custom routers
from bloomerp.views.workspace import router as dashboard_router
from bloomerp.views.core import router as core_router
from bloomerp.views.widgets import router as widget_router
from bloomerp.views.auth import router as auth_router
from django.apps import apps
custom_routers = _get_routers_from_settings()


custom_routers.append(document_template_router)
custom_routers.append(dashboard_router)
custom_routers.append(core_router)
custom_routers.append(widget_router)
custom_routers.append(auth_router)

custom_router_handler = BloomerpRouterHandler(custom_routers)

if settings.BLOOMERP_SETTINGS.get('AUTO_GENERATE_LINKS', False):
    custom_router_handler.generate_links()

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
# App level routes
# ---------------------------------
app_level_routes = custom_router_handler.get_app_routes()
for route in app_level_routes:
    urlpatterns.append(route.create_urlpattern())


# ---------------------------------
# Model related URL patterns
# ---------------------------------
content_types = ContentType.objects.all()


for content_type in content_types:
    if content_type.model_class():
        # Detail view patterns
        detail_view_patterns = []
        
        # Initialize some variables
        model : Model = content_type.model_class()
        base_model_route = get_base_model_route(model, include_slash=False) # Example: CustomerInvoice -> customer-invoices
        model_name_underline = model_name_plural_underline(model)
        model_name_plural = model._meta.verbose_name_plural
        model_name = model._meta.verbose_name

        
        # ---------------------------------
        # Custom routes
        # ---------------------------------
        custom_detail_view_routes = custom_router_handler.get_detail_view_routes_for_model(model)
        custom_list_view_routes = custom_router_handler.get_list_view_routes_for_model(model)
            
        for route in custom_detail_view_routes:
            # create the URL pattern
            urlpatterns.append(route.create_urlpattern())


        for route in custom_list_view_routes:
            # create the URL pattern
            urlpatterns.append(route.create_urlpattern())
            

        # ---------------------------------
        # Rest framework URL patterns
        # ---------------------------------
        # Generate the serializer class
        serializer_class = generate_serializer(model)

        # Generate the viewset class
        ApiViewSet = generate_model_viewset_class(
            model=model,
            serializer=serializer_class,
            base_viewset=BloomerpModelViewSet
        )

        try:

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


# ---------------------------------
# API URL patterns
# ---------------------------------

urlpatterns += [
    path('api/', include(drf_router.urls)),
]

# ---------------------------------
# Route decorator
# ---------------------------------
# Get current dir
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
components_dir = os.path.join(current_dir, 'components')

route_finder = RouteFinder(directory=components_dir, url_route_prefix='components/', url_name_prefix='components')
urlpatterns += route_finder.generate_urlpatterns()


# ---------------------------------
# Create path
# ---------------------------------

BLOOMERP_URLPATTERNS = path(BASE_URL, include(urlpatterns))
