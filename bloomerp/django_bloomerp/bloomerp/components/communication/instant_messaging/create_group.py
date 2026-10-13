"""Dispatch registered provider creation flows through a shared component endpoint."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.utils.module_loading import import_string
from django.views.decorators.http import require_http_methods
from bloomerp.communication.builtins.instant_messaging.registry import (
    IM_PROVIDER_REGISTRY,
)
from bloomerp.router import router


@router.register(
    path="components/communication/im/groups/create/",
    url_name="components_im_create_group",
)
@login_required
@require_http_methods(["GET", "POST"])
def create_group(request: HttpRequest) -> HttpResponse:
    """Resolve the requested action from its provider and authorize both GET and POST."""
    data = request.POST if request.method == "POST" else request.GET
    provider = IM_PROVIDER_REGISTRY.get(data.get("provider", ""))
    action = (
        next(
            (
                item
                for item in provider.creation_actions
                if item.key == data.get("action")
            ),
            None,
        )
        if provider
        else None
    )
    if action is None:
        return HttpResponse(status=400)
    if not import_string(action.permission_resolver)(request):
        raise PermissionDenied
    return import_string(action.handler)(request, provider, action)
