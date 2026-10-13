"""Signed delivery acknowledgments for previously authorized outbound messages."""

from bloomerp.models.communication.voip import VoIPConnection

from uuid import UUID
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from bloomerp.communication.builtins.voip.controller import notify_conversation
from bloomerp.models.communication.instant_messaging import IMMessage


def message_status(
    request: HttpRequest, connection: VoIPConnection, message_id: UUID
) -> HttpResponse:
    """Reconcile callbacks without regressing delivered messages or crossing accounts."""
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
