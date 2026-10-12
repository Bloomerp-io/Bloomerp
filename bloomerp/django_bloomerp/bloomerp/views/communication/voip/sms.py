"""Signed incoming SMS delivery into the shared phone conversation timeline."""

from uuid import UUID
from functools import partial
from django.db import transaction
from django.db.models import Max
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from bloomerp.router import router
from bloomerp.communication.builtins.voip.webhooks import (
    verified_connection,
    incoming_conversation,
)
from bloomerp.models.communication.instant_messaging import IMMessage, IMConversation
from bloomerp.communication.builtins.instant_messaging.controller import IMController


@router.register(
    path="communication/voip/<uuid:connection_id>/sms/", url_name="voip_sms"
)
@csrf_exempt
@require_POST
@transaction.atomic
def sms(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    """Deduplicate carrier message IDs under the conversation lock before notifying staff."""
    connection = verified_connection(request, connection_id, "sms")
    number = get_object_or_404(
        connection.numbers,
        number=request.POST.get("To"),
        is_active=True,
        supports_sms=True,
    )
    if not request.POST.get("MessageSid") or not request.POST.get(
        "From", ""
    ).startswith("+"):
        return HttpResponse(status=400)
    chat = incoming_conversation(number, request.POST["From"])
    IMConversation.objects.select_for_update().get(pk=chat.pk)
    if not chat.messages.filter(
        provider_message_id=request.POST["MessageSid"]
    ).exists():
        message = IMMessage.objects.create(
            conversation=chat,
            sender=chat.participants.get(identity__address=request.POST["From"]),
            sequence=(chat.messages.aggregate(last=Max("sequence"))["last"] or 0) + 1,
            body=request.POST.get("Body", ""),
            direction="inbound",
            status="delivered",
            received_at=timezone.now(),
            provider_message_id=request.POST["MessageSid"],
        )
        chat.last_activity_at = timezone.now()
        chat.save(update_fields=["last_activity_at"])
        transaction.on_commit(partial(IMController.notify_message, message.pk))
    return HttpResponse("<Response/>", content_type="application/xml")
