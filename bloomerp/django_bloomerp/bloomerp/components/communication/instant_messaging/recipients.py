"""Recipient picker content rendered inside the standard Cotton dropdown."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.communication.builtins.instant_messaging.definition import (
    IMConnectionContext,
)
from bloomerp.communication.builtins.instant_messaging.registry import (
    IM_PROVIDER_REGISTRY,
)
from bloomerp.models.communication.instant_messaging import IMConnection
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/communication/im/recipients/", url_name="components_im_recipients"
)
@login_required
@require_GET
def recipients(request: HttpRequest) -> HttpResponse:
    """Return the staff messaging directory with the provider's typed cursor."""
    query = request.GET.get("recipient_query", "").strip()[:200]
    try:
        page = IMController(request.user).discover_recipients(
            query, request.GET.get("cursor")
        )
    except ValueError:
        return HttpResponse(status=400)
    provider = IM_PROVIDER_REGISTRY.get("internal")
    capabilities = (
        provider.create_adapter(
            IMConnectionContext(None, provider.key, actor_id=str(request.user.pk))
        )
        .validate_connection()
        .capabilities
    )
    response = render(
        request,
        "components/communication/instant_messaging/recipients.html",
        {
            "page": page,
            "can_create_group": request.user.is_active
            and request.user.is_staff
            and capabilities.create_groups,
            "query": query,
            "connections": UserPolicyManager(request.user).get_accessible_queryset(
                IMConnection, "view"
            ),
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response
