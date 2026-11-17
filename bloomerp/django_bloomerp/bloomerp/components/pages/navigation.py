"""Render the same grouped page history in the sidebar and scratchpad."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from bloomerp.router import router
from bloomerp.services.page_services import page_context


@router.register(
    path="components/pages/navigation/", url_name="components_pages_navigation"
)
@login_required
@never_cache
@require_GET
def page_navigation(request: HttpRequest) -> HttpResponse:
    """Return model-owned Recent, Shared and Private queries for the current user."""
    return render(request, "components/pages/navigation.html", page_context(request))
