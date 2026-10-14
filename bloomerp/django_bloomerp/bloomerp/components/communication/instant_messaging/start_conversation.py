"""Start a native conversation from a revalidated recipient selection."""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_POST

from bloomerp.router import router

from .conversation import render_conversation


@router.register(
    path="components/communication/im/start/",
    url_name="components_im_start_conversation",
)
@login_required
@require_POST
def start_conversation(request: HttpRequest) -> HttpResponse:
    """Create or reuse an internal direct chat and return its reusable fragment."""
    from django.shortcuts import render
    from bloomerp.utils.callables import resolve_hook
    from bloomerp.communication.builtins.instant_messaging.registry import (
        IM_PROVIDER_REGISTRY,
    )
    from bloomerp.communication.builtins.instant_messaging.selection import (
        resolve_steps,
    )

    provider = IM_PROVIDER_REGISTRY.get(request.POST.get("provider", "internal"))
    if provider is None or not provider.start_handler:
        return HttpResponse(status=400)
    if (
        not request.POST.get("recipient_id")
        and request.POST.get("provider", "internal") == "internal"
    ):
        return HttpResponse(status=400)
    try:
        selected, step, options = resolve_steps(
            provider, request.user, request.POST.dict()
        )
        if step:
            response = render(
                request,
                "components/communication/instant_messaging/selection.html",
                {
                    "provider": provider,
                    "selected": selected,
                    "step": step,
                    "options": options.items,
                },
            )
            response["HX-Trigger"] = json.dumps(
                {
                    "im:selection-opened": {
                        "target": "[bloomerp-component='bloomerp:messaging-panel']"
                    }
                }
            )
            response["Cache-Control"] = "private, no-store"
            return response
        chat = resolve_hook(provider.start_handler)(request.user, selected)
    except (ValueError, ValidationError):
        return HttpResponse(status=400)
    response = render_conversation(request, chat.pk)
    response["HX-Trigger"] = json.dumps(
        {
            "im:conversation-opened": {
                "id": str(chat.pk),
                "target": "[bloomerp-component='bloomerp:messaging-panel']",
            }
        }
    )
    return response
