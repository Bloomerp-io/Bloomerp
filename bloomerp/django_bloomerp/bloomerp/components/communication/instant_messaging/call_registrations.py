"""Discover incoming browser registrations from capable IM provider definitions."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.instant_messaging.registry import (
    IM_PROVIDER_REGISTRY,
)
from bloomerp.router import router
from bloomerp.utils.callables import resolve_hook


@router.register(
    path="components/communication/calling/registrations/",
    url_name="components_im_call_registrations",
)
@login_required
@require_GET
def call_registrations(request: HttpRequest) -> JsonResponse:
    """Let provider hooks return only the actor's currently authorized registrations."""
    registrations: list[dict[str, str]] = []
    for provider in IM_PROVIDER_REGISTRY.values():
        if provider.calling and provider.calling.registrations_resolver:
            registrations.extend(
                {**registration, "driver": provider.calling.browser_driver}
                for registration in resolve_hook(
                    provider.calling.registrations_resolver
                )(request.user)
            )
    return JsonResponse(
        {"registrations": registrations}, headers={"Cache-Control": "private, no-store"}
    )
