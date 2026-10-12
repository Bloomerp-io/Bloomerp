"""Signed TwiML routing for authorized browser sessions and incoming calls."""

from uuid import UUID
import re
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from twilio.twiml.voice_response import VoiceResponse
from bloomerp.router import router
from bloomerp.models.communication.voip import PhoneCall
from bloomerp.communication.builtins.voip.webhooks import (
    verified_connection,
    incoming_conversation,
)
from bloomerp.communication.builtins.voip.controller import (
    callback_url,
    VoIPController,
    project_call,
    notify_conversation,
)


@router.register(
    path="communication/voip/<uuid:connection_id>/voice/", url_name="voip_voice"
)
@csrf_exempt
@require_POST
@transaction.atomic
def voice(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    """Generate routing instructions only after validating carrier signature and current access."""
    connection = verified_connection(request, connection_id, "voice")
    response = VoiceResponse()
    if request.POST.get("From", "").startswith("client:"):
        try:
            call_id = UUID(request.POST.get("CallId", ""))
        except ValueError:
            return HttpResponse(status=400)
        call = get_object_or_404(
            PhoneCall.objects.select_for_update(),
            pk=call_id,
            connection=connection,
            direction="outbound",
        )
        expected = f"client:bloomerp_{connection.pk.hex}_{call.handled_by_id}"
        if request.POST.get("From") != expected or not call.handled_by_id:
            raise PermissionDenied
        VoIPController(call.handled_by).conversation(call.conversation_id)
        if call.provider_call_id and call.provider_call_id != request.POST.get(
            "CallSid"
        ):
            raise PermissionDenied
        if call.status not in {"pending", "queued", "ringing", "in-progress"}:
            response.hangup()
        else:
            call.provider_call_id = request.POST["CallSid"]
            call.save(update_fields=["provider_call_id"])
            dial = response.dial(
                caller_id=call.from_address,
                answer_on_bridge=True,
                action=callback_url(connection, "call_status"),
                method="POST",
            )
            dial.number(
                call.to_address,
                status_callback=callback_url(connection, "call_status"),
                status_callback_method="POST",
                status_callback_event="initiated ringing answered completed",
            )
    else:
        number = get_object_or_404(
            connection.numbers,
            number=request.POST.get("To"),
            is_active=True,
            supports_voice=True,
        )
        address = request.POST.get("From", "")
        chat = (
            incoming_conversation(number, address)
            if re.fullmatch(r"\+[1-9]\d{1,14}", address)
            else None
        )
        call, created = PhoneCall.objects.get_or_create(
            connection=connection,
            provider_call_id=request.POST["CallSid"],
            defaults={
                "number": number,
                "conversation": chat,
                "direction": "inbound",
                "from_address": request.POST.get("From", ""),
                "to_address": number.number,
                "status": "ringing",
                "started_at": timezone.now(),
            },
        )
        project_call(call)
        from functools import partial

        if chat:
            transaction.on_commit(partial(notify_conversation, chat.pk))
        users = list(number.assigned_users.filter(is_active=True, is_staff=True)[:10])
        if not users or not connection.settings.get("browser_calling"):
            response.reject(reason="busy")
        else:
            dial = response.dial(
                answer_on_bridge=True,
                action=callback_url(connection, "call_status"),
                method="POST",
            )
            for user in users:
                dial.client(
                    f"bloomerp_{connection.pk.hex}_{user.pk}",
                    status_callback=callback_url(connection, "call_status"),
                    status_callback_method="POST",
                    status_callback_event="initiated ringing answered completed",
                )
    return HttpResponse(str(response), content_type="application/xml")
