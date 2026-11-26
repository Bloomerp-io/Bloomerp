from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from bloomerp.models.workspaces.sidebar import Sidebar
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager


@router.register(
    path="components/ui/sidebar/preferences/",
    url_name="components_sidebar_preferences",
)
@login_required
@require_GET
def sidebar_preferences(request: HttpRequest) -> HttpResponse:
    """Render the selected sidebar's links and management controls."""
    sidebar = PreferenceManager(request.user).get_or_create_selected(Sidebar)
    return render(request, "components/ui/sidebar/preferences.html", {"sidebar": sidebar})
