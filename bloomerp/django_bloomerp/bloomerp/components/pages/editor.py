"""Load the same page editor into the floating scratchpad."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from bloomerp.router import router
from bloomerp.services.page_services import page_context


@router.register(path="components/pages/editor/", url_name="components_pages_editor")
@login_required
@never_cache
@require_GET
def page_editor(request: HttpRequest) -> HttpResponse:
    """Render an authorized page or a blank draft for the scratchpad."""
    return render(request, "components/pages/editor.html", page_context(request))
