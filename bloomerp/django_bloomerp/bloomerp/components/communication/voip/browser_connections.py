"""Discover authorized browser registrations without exposing credentials."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET
from bloomerp.router import router
from bloomerp.communication.builtins.voip.access import VoIPAccessManager


@router.register(
    path="components/communication/voip/browser-connections/",
    url_name="components_voip_browser_connections",
)
@login_required
@require_GET
def browser_connections(request: HttpRequest) -> JsonResponse:
    """Return distinct active carrier accounts with at least one authorized voice line."""
    ids = (
        VoIPAccessManager(request.user)
        .get_numbers()
        .filter(supports_voice=True, connection__settings__browser_calling=True)
        .values_list("connection_id", flat=True)
        .distinct()
    )
    return JsonResponse(
        {
            "connections": [
                {
                    "id": str(pk),
                    "token_url": reverse(
                        "components_voip_token", kwargs={"connection_id": pk}
                    ),
                }
                for pk in ids
            ]
        },
        headers={"Cache-Control": "private, no-store"},
    )
