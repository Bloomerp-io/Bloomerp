"""Shared Twilio request verification and incoming conversation reconciliation."""

from typing import Any
from uuid import UUID
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.db import transaction
from bloomerp.models.communication.voip import VoIPConnection, VoIPNumber
from . import controller
from .controller import callback_url
from .builtins.twilio import TwilioAdapter


def verified_connection(
    request: HttpRequest, connection_id: UUID, kind: str, **kwargs: Any
) -> VoIPConnection:
    """Verify signatures against the configured public URL, never an untrusted Host header."""
    connection = get_object_or_404(
        VoIPConnection, pk=connection_id, provider="twilio", status="active"
    )
    adapter = controller.adapter_for(connection)
    if not isinstance(adapter, TwilioAdapter) or not adapter.verify_webhook(
        callback_url(connection, kind, **kwargs),
        request.POST,
        request.headers.get("X-Twilio-Signature", ""),
    ):
        raise PermissionDenied
    return connection


@transaction.atomic
def incoming_conversation(number: VoIPNumber, address: str) -> Any:
    """Create or reuse an incoming phone conversation and enroll assigned staff."""
    from bloomerp.models.communication.instant_messaging import (
        IMConversation,
        IMConversationParticipant,
        IMIdentity,
    )

    VoIPNumber.objects.select_for_update().get(pk=number.pk)
    identity, created = IMIdentity.objects.get_or_create(
        provider_key="phone",
        connection=None,
        external_id=address,
        defaults={"address": address, "display_name": address},
    )
    chat, created = IMConversation.objects.get_or_create(
        provider_key="phone", voip_number=number, phone_address=address
    )
    IMConversationParticipant.objects.get_or_create(
        conversation=chat, identity=identity
    )
    for user in number.assigned_users.filter(is_active=True, is_staff=True):
        IMConversationParticipant.objects.get_or_create(conversation=chat, user=user)
    return chat
