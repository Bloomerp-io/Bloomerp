"""Signed delivery acknowledgments for previously authorized outbound messages."""

from uuid import UUID
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from bloomerp.router import router
from bloomerp.communication.builtins.voip.webhooks import verified_connection
from bloomerp.communication.builtins.voip.controller import notify_conversation
from bloomerp.models.communication.instant_messaging import IMMessage


@router.register(
    path="communication/voip/<uuid:connection_id>/messages/<uuid:message_id>/status/",
    url_name="voip_message_status",
)
@csrf_exempt
@require_POST
def message_status(
    request: HttpRequest, connection_id: UUID, message_id: UUID
) -> HttpResponse:
    """Reconcile callbacks without regressing delivered messages or crossing accounts."""
    connection = verified_connection(
        request, connection_id, "message_status", message_id=message_id
    )
    statuses = {
        "accepted": "accepted",
        "queued": "accepted",
        "sending": "accepted",
        "sent": "sent",
        "delivered": "delivered",
        "undelivered": "failed",
        "failed": "failed",
    }
    status = statuses.get(request.POST.get("MessageStatus"))
    if status is None or not request.POST.get("MessageSid"):
        return HttpResponse(status=400)
    with transaction.atomic():
        message = get_object_or_404(
            IMMessage.objects.select_for_update(),
            pk=message_id,
            conversation__voip_number__connection=connection,
            direction="outbound",
        )
        if (
            message.provider_message_id
            and message.provider_message_id != request.POST["MessageSid"]
        ):
            return HttpResponse(status=400)
        ranks = {
            "pending": 0,
            "accepted": 1,
            "sent": 2,
            "failed": 3,
            "delivered": 4,
            "read": 5,
        }
        if ranks[status] > ranks[message.status]:
            message.status = status
        message.provider_message_id = request.POST["MessageSid"]
        message.save()
    notify_conversation(message.conversation_id)
    return HttpResponse(status=204)
