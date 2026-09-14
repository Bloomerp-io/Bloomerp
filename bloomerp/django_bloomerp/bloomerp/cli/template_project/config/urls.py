from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.conf import settings

# Register generated views independently of user-owned URL extensions.
from django.apps import apps
from importlib import import_module

if apps.is_installed("project_app"):
    for module in ("project_app.views.config.create_user", "project_app.views.config.users", "project_app.views.generated"):
        import_module(module)


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
    path("", include("bloomerp.urls")),
    path("", include("config.project_urls")),
]

if settings.DEBUG:
    urlpatterns.append(
        path("__reload__/", include("django_browser_reload.urls")),
    )
