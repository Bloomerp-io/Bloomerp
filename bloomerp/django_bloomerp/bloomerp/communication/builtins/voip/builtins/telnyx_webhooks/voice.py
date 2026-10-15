"""Route signed Telnyx requests using current line authorization and opaque reservations."""

import re
from functools import partial
from xml.etree.ElementTree import Element, SubElement, tostring

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from bloomerp.communication.builtins.voip.controller import (
    VoIPController,
    adapter_for,
    notify_conversation,
    project_call,
)
from bloomerp.communication.builtins.voip.webhooks import incoming_conversation
from bloomerp.models.communication.voip import PhoneCall, VoIPConnection


def xml_response(root: Element) -> HttpResponse:
    """Serialize TeXML with escaping for all provider and application values."""
    return HttpResponse(
        tostring(root, encoding="unicode"), content_type="application/xml"
    )


@transaction.atomic
def voice(request: HttpRequest, connection: VoIPConnection) -> HttpResponse:
    """Resolve outgoing reservations or ring currently assigned staff for an owned number."""
    adapter = adapter_for(connection)
    root = Element("Response")
    data = request.POST
    call_sid = data.get("CallSid", "")
    if not call_sid or len(call_sid) > 255:
        return HttpResponse(status=400)
    destination = data.get("To", "")
    domain = f"{connection.settings['sip_subdomain']}.sip.telnyx.com"
    outgoing = not re.fullmatch(r"\+[1-9]\d{1,14}", destination)
    if outgoing:
        sip_destination = data.get("ToSipUri") or destination
        reference, separator, host = sip_destination.removeprefix("sip:").partition("@")
        if not separator or host != domain:
            raise PermissionDenied
        try:
            call_id = adapter.resolve_call_reference(reference)
        except (signing.BadSignature, ValueError) as error:
            raise PermissionDenied from error
        call = get_object_or_404(
            PhoneCall.objects.select_for_update(),
            pk=call_id,
            connection=connection,
            direction="outbound",
        )
        if not call.handled_by_id or not call.conversation_id:
            raise PermissionDenied
        VoIPController(call.handled_by).conversation(call.conversation_id)
        if call.provider_call_id and call.provider_call_id != call_sid:
            raise PermissionDenied
        if call.status not in {"pending", "queued", "ringing", "in-progress"}:
            SubElement(root, "Hangup")
            return xml_response(root)
        call.provider_call_id = call_sid
        call.save(update_fields=["provider_call_id"])
        targets = [("Number", call.to_address)]
        caller_id = call.from_address
    else:
        number = get_object_or_404(
            connection.numbers, number=destination, is_active=True, supports_voice=True
        )
        address = data.get("From", "")
        chat = (
            incoming_conversation(number, address)
            if re.fullmatch(r"\+[1-9]\d{1,14}", address)
            else None
        )
        call, created = PhoneCall.objects.get_or_create(
            connection=connection,
            provider_call_id=call_sid,
            defaults={
                "number": number,
                "conversation": chat,
                "direction": "inbound",
                "from_address": address,
                "to_address": number.number,
                "status": "ringing",
                "started_at": timezone.now(),
            },
        )
        if call.status in {"completed", "busy", "no-answer", "canceled", "failed"}:
            SubElement(root, "Hangup")
            return xml_response(root)
        if created:
            project_call(call)
            if chat:
                transaction.on_commit(partial(notify_conversation, chat.pk))
        targets = []
        if connection.settings.get("browser_calling"):
            identities = {
                f"bloomerp_{connection.pk.hex}_{user.pk}"
                for user in number.assigned_users.filter(is_active=True, is_staff=True)
            }
            for credential in adapter.credentials_for_identities(identities):
                username = credential.get("sip_username", "")
                if re.fullmatch(r"[A-Za-z0-9_-]+", username):
                    targets.append(("Sip", f"sip:{username}@sip.telnyx.com"))
        caller_id = (
            address if re.fullmatch(r"\+[1-9]\d{1,14}", address) else number.number
        )
    if not targets:
        SubElement(root, "Reject", reason="busy")
    else:
        callback = adapter.callback_url("call_status")
        dial = SubElement(
            root,
            "Dial",
            callerId=caller_id,
            answerOnBridge="true",
            action=callback,
            method="POST",
        )
        for kind, address in targets:
            SubElement(
                dial,
                kind,
                statusCallback=callback,
                statusCallbackMethod="POST",
                statusCallbackEvent="initiated ringing answered completed",
            ).text = address
    return xml_response(root)
