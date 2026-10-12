"""Recipient picker content rendered inside the standard Cotton dropdown."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.instant_messaging.registry import (
    IM_PROVIDER_REGISTRY,
)
from bloomerp.router import router


@router.register(
    path="components/communication/im/recipients/", url_name="components_im_recipients"
)
@login_required
@require_GET
def recipients(request: HttpRequest) -> HttpResponse:
    """Return the staff messaging directory with the provider's typed cursor."""
    from django.core.exceptions import ValidationError
    from bloomerp.communication.builtins.instant_messaging.selection import (
        resolve_steps,
    )

    query = request.GET.get("recipient_query", "").strip()[:200]
    groups = []
    try:
        for provider in IM_PROVIDER_REGISTRY.values():
            if request.GET.get("provider") and request.GET["provider"] != provider.key:
                continue
            if not provider.selection_steps:
                continue
            selected, step, options = resolve_steps(
                provider, request.user, {}, query, request.GET.get("cursor", "")
            )
            groups.append(
                {
                    "provider": provider,
                    "step": step,
                    "options": options.items,
                    "next_cursor": options.next_cursor,
                    "selected": selected,
                }
            )
    except (ValueError, ValidationError):
        return HttpResponse(status=400)
    response = render(
        request,
        "components/communication/instant_messaging/recipients.html",
        {
            "groups": groups,
            "can_create_group": request.user.is_active and request.user.is_staff,
            "query": query,
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response
