"""Provider-dispatched request verification and incoming conversation reconciliation."""

from typing import Any
from uuid import UUID
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from bloomerp.models.communication.voip import VoIPConnection, VoIPNumber
from . import controller
from django.utils.module_loading import import_string
from .registry import VOIP_PROVIDER_REGISTRY


def verified_connection(
    request: HttpRequest, connection_id: UUID, kind: str, **kwargs: Any
) -> VoIPConnection:
    """Verify signatures against the configured public URL, never an untrusted Host header."""
    connection = get_object_or_404(VoIPConnection, pk=connection_id, status="active")
    adapter = controller.adapter_for(connection)
    if not adapter.verify_request(request, kind, **kwargs):
        raise PermissionDenied
    return connection


def dispatch_webhook(
    request: HttpRequest, connection_id: UUID, kind: str, **kwargs: Any
) -> HttpResponse:
    """Select a registered handler without interpreting another carrier's payload format."""
    connection = get_object_or_404(VoIPConnection, pk=connection_id, status="active")
    provider = VOIP_PROVIDER_REGISTRY.get(connection.provider)
    handler = provider.webhook_handlers.get(kind) if provider else None
    if handler is None:
        raise PermissionDenied
    connection = verified_connection(request, connection_id, kind, **kwargs)
    return import_string(handler)(request, connection, **kwargs)


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
