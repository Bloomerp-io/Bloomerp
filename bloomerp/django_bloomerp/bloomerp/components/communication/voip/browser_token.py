"""Short-lived browser authorization scoped to accessible carrier lines."""

from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _
from bloomerp.router import router
from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.communication.builtins.voip.controller import adapter_for
from bloomerp.communication.builtins.voip.registry import VOIP_PROVIDER_REGISTRY


@router.register(
    path="components/communication/voip/<uuid:connection_id>/token/",
    url_name="components_voip_token",
)
@login_required
@require_POST
def browser_token(request: HttpRequest, connection_id: UUID) -> JsonResponse:
    """Issue tokens only while this actor has an active voice-enabled number."""
    number = (
        VoIPAccessManager(request.user)
        .get_numbers()
        .select_related("connection")
        .filter(
            connection_id=connection_id,
            supports_voice=True,
            connection__settings__browser_calling=True,
        )
        .first()
    )
    if number is None:
        return JsonResponse({"error": _("Browser calling is unavailable.")}, status=403)
    provider = VOIP_PROVIDER_REGISTRY.get(number.connection.provider)
    if not provider.browser_driver:
        return JsonResponse({"error": _("Browser calling is unavailable.")}, status=403)
    token = adapter_for(number.connection).browser_token(
        f"bloomerp_{number.connection.pk.hex}_{request.user.pk}"
    )
    return JsonResponse(
        {"token": token, "driver": provider.browser_driver},
        headers={"Cache-Control": "private, no-store"},
    )
