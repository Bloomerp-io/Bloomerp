"""Native IM creation action for a solo, shareable meeting."""

from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from bloomerp.communication.builtins.instant_messaging.definition import (
    IMCreationAction,
    IMProviderDefinition,
)
from bloomerp.config.definition import get_bloomerp_config
from bloomerp.models.communication.conferencing import ConferenceRoom

from .controller import ConferenceController, ConferenceUnavailable, session_payload


def can_start_meeting(request: HttpRequest) -> bool:
    """Expose native solo meetings only to active staff with conferencing enabled."""
    return (
        request.user.is_authenticated
        and request.user.is_active
        and request.user.is_staff
        and get_bloomerp_config().conferencing.enabled
    )


def start_meeting(
    request: HttpRequest, provider: IMProviderDefinition, action: IMCreationAction
) -> HttpResponse:
    """Render a call action or reserve an idempotent room with only its creator invited."""
    if request.method == "GET":
        url = (
            reverse("components_im_create_group")
            + "?"
            + urlencode({"provider": provider.key, "action": action.key})
        )
        return render(
            request,
            "components/communication/conferencing/start_meeting.html",
            {"start_url": url},
        )
    try:
        client_id = str(UUID(request.POST.get("client_id", "")))
        room, _created = ConferenceRoom.objects.get_or_create(
            pk=uuid5(NAMESPACE_URL, f"bloomerp-meeting:{request.user.pk}:{client_id}"),
            defaults={"title": _("Meeting"), "created_by": request.user},
        )
        session = ConferenceController(request.user).start(
            room, [request.user], request.POST.get("media_mode", "video"), client_id
        )
    except (ValueError, ValidationError):
        return JsonResponse({"error": _("Unable to start this meeting.")}, status=400)
    except (ConferenceUnavailable, ImproperlyConfigured):
        return JsonResponse(
            {"error": _("Conferencing is unavailable. Please retry.")}, status=503
        )
    return JsonResponse(session_payload(session), headers={"Cache-Control": "no-store"})
