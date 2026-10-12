"""Authorized reservation of browser call sessions."""

from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _
from bloomerp.router import router
from bloomerp.communication.builtins.voip.controller import VoIPController


@router.register(
    path="components/communication/voip/conversation/<uuid:conversation_id>/call/",
    url_name="components_voip_start_call",
)
@login_required
@require_POST
def start_call(request: HttpRequest, conversation_id: UUID) -> JsonResponse:
    """Reserve a call before the Voice SDK requests signed TwiML routing."""
    try:
        controller = VoIPController(request.user)
        if request.POST.get("action") == "cancel":
            call = controller.cancel_reservation(
                conversation_id, UUID(request.POST.get("call_id", ""))
            )
        else:
            call = controller.prepare_call(
                conversation_id, request.POST.get("client_id", "")
            )
    except (ValidationError, ValueError):
        return JsonResponse({"error": _("Calling is unavailable.")}, status=400)
    return JsonResponse(
        {"call_id": str(call.pk)}, headers={"Cache-Control": "private, no-store"}
    )
