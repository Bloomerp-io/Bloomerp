"""Adapt carrier calls to the common IM calling contract without conference records."""

from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from bloomerp.communication.builtins.instant_messaging.definition import (
    IMCallCapabilities,
)
from bloomerp.models.communication.instant_messaging import IMConversation
from bloomerp.models.users.user import AbstractBloomerpUser

from .access import VoIPAccessManager
from .controller import VoIPController, adapter_for
from .registry import VOIP_PROVIDER_REGISTRY


def capabilities(
    user: AbstractBloomerpUser, chat: IMConversation
) -> IMCallCapabilities:
    """Advertise browser audio only for a currently authorized voice line and driver."""
    number = (
        VoIPAccessManager(user)
        .get_numbers()
        .select_related("connection")
        .filter(pk=chat.voip_number_id)
        .first()
    )
    if number is None:
        return IMCallCapabilities()
    provider = VOIP_PROVIDER_REGISTRY.get(number.connection.provider)
    return IMCallCapabilities(
        audio=bool(
            number.supports_voice
            and number.connection.settings.get("browser_calling")
            and provider
            and provider.browser_driver
        )
    )


def participants(
    user: AbstractBloomerpUser, chat: IMConversation
) -> list[AbstractBloomerpUser]:
    """Resolve the authorized local actor; remote telephone identities remain carrier-owned."""
    VoIPController(user).conversation(chat.pk)
    return [user]


def start(
    user: AbstractBloomerpUser, chat: IMConversation, media_mode: str, client_id: str
) -> dict[str, str]:
    """Reserve a PhoneCall and return the same session navigation contract as conferencing."""
    if media_mode != "audio" or not capabilities(user, chat).audio:
        raise PermissionDenied
    call = VoIPController(user).prepare_call(chat.pk, client_id)
    if call.status != "pending" or call.provider_call_id:
        raise ValidationError("This phone call has already been submitted.")
    return {
        "session_id": str(call.pk),
        "media_mode": "audio",
        "status": call.status,
        "join_url": reverse("components_voip_join_call", kwargs={"call_id": call.pk}),
        "cancel_url": reverse(
            "components_voip_cancel_call", kwargs={"call_id": call.pk}
        ),
        "end_url": "",
        "can_end": "false",
    }


def join(user: AbstractBloomerpUser, call_id: UUID) -> dict[str, Any]:
    """Recheck ownership and line access before exposing credentials for a reserved call."""
    call = (
        VoIPAccessManager(user)
        .get_calls()
        .select_related("conversation", "connection")
        .filter(pk=call_id, handled_by=user)
        .first()
    )
    if call is None or call.conversation is None:
        raise PermissionDenied
    VoIPController(user).conversation(call.conversation_id)
    if not capabilities(user, call.conversation).audio:
        raise PermissionDenied
    if call.status != "pending" or call.provider_call_id:
        raise ValidationError("This phone call has already been submitted.")
    from bloomerp.communication.builtins.instant_messaging.calling import (
        calling_definition,
    )

    provider = VOIP_PROVIDER_REGISTRY.get(call.connection.provider)
    definition = calling_definition(call.conversation)
    if definition is None or provider is None:
        raise PermissionDenied
    from bloomerp.communication.builtins.instant_messaging.presentation import (
        participant_identity,
    )

    identities = [
        {
            "id": str(member.pk),
            "local": member.user_id == user.pk,
            **participant_identity(member, user.pk),
        }
        for member in call.conversation.participants.select_related(
            "user", "identity", "conversation"
        ).filter(left_at__isnull=True)
        if member.user_id == user.pk or member.identity_id
    ]
    return {
        "participants": identities,
        "session_id": str(call.pk),
        "call_id": adapter_for(call.connection).browser_call_reference(call.pk),
        "media_mode": "audio",
        "join_url": reverse("components_voip_join_call", kwargs={"call_id": call.pk}),
        "cancel_url": reverse(
            "components_voip_cancel_call", kwargs={"call_id": call.pk}
        ),
        "end_url": "",
        "can_end": "false",
        "can_video": "false",
        "can_screen_share": "false",
        "driver": definition.browser_driver,
        "carrier_driver": provider.browser_driver,
        "registration_id": str(call.connection_id),
        "token_url": reverse(
            "components_voip_token", kwargs={"connection_id": call.connection_id}
        ),
        "token": adapter_for(call.connection).browser_token(
            f"bloomerp_{call.connection.pk.hex}_{user.pk}"
        ),
        "url": "",
    }


def registrations(user: AbstractBloomerpUser) -> list[dict[str, str]]:
    """Declare incoming registration endpoints through the IM provider hook."""
    numbers = (
        VoIPAccessManager(user)
        .get_numbers()
        .select_related("connection")
        .filter(supports_voice=True, connection__settings__browser_calling=True)
    )
    result: dict[str, dict[str, str]] = {}
    for number in numbers:
        provider = VOIP_PROVIDER_REGISTRY.get(number.connection.provider)
        if provider and provider.browser_driver:
            key = str(number.connection_id)
            result[key] = {
                "id": key,
                "token_url": reverse(
                    "components_voip_token",
                    kwargs={"connection_id": number.connection_id},
                ),
            }
    return list(result.values())
