"""Provider-dispatched call initiation from any capable IM conversation."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.controller import (
    ConferenceUnavailable,
)
from bloomerp.communication.builtins.instant_messaging.calling import (
    start_call as dispatch_call,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conversation/<uuid:conversation_id>/call/",
    url_name="components_im_start_call",
)
@login_required
@require_POST
def start_call(request: HttpRequest, conversation_id: UUID) -> JsonResponse:
    """Start a call through provider hooks, returning session endpoints to the client."""
    headers = {"Cache-Control": "private, no-store"}
    try:
        payload = dispatch_call(
            request.user,
            conversation_id,
            request.POST.get("media_mode", ""),
            request.POST.get("client_id", ""),
        )
    except ValidationError as error:
        conflict = getattr(error, "code", None) == "call_already_open"
        return JsonResponse(
            {"error": (
                _("A call is already open. Use Join call in the conversation.")
                if conflict else _("Calling is unavailable or the request is invalid.")
            )},
            status=409 if conflict else 400,
            headers=headers,
        )
    except (ConferenceUnavailable, ImproperlyConfigured):
        return JsonResponse(
            {
                "error": _(
                    "The media service is unavailable. Retry with the same request identifier."
                )
            },
            status=503,
            headers=headers,
        )
    return JsonResponse(payload, headers=headers)
