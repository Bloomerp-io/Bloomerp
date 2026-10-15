"""Cancel an unsubmitted carrier reservation through a provider-owned URL."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.voip.access import VoIPAccessManager
from bloomerp.communication.builtins.voip.controller import VoIPController
from bloomerp.router import router


@router.register(
    path="components/communication/voip/calls/<uuid:call_id>/cancel/",
    url_name="components_voip_cancel_call",
)
@login_required
@require_POST
def cancel_call(request: HttpRequest, call_id: UUID) -> JsonResponse:
    """Close only the actor's pending reservation, leaving connected calls to their SDK."""
    call = (
        VoIPAccessManager(request.user)
        .get_calls()
        .filter(pk=call_id, handled_by=request.user)
        .first()
    )
    if call is None or call.conversation_id is None:
        raise PermissionDenied
    call = VoIPController(request.user).cancel_reservation(
        call.conversation_id, call_id
    )
    return JsonResponse(
        {"session_id": str(call.pk), "status": call.status},
        headers={"Cache-Control": "private, no-store"},
    )
