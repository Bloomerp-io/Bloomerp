"""Resolve saved conversation identities through registered provider definitions."""

from typing import Any
from urllib.parse import urlsplit

from django.utils.translation import gettext as _

from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
)

from .registry import IM_PROVIDER_REGISTRY


def participant_label(participant: IMConversationParticipant) -> str:
    """Return the visible author label for either a staff or provider identity."""
    if participant.user_id:
        return participant.user.get_full_name() or participant.user.get_username()
    return (
        participant.identity.display_name
        or participant.identity.address
        or participant.identity.external_id
    )


def conversation_identity(conversation: IMConversation, user_id: Any) -> dict[str, Any]:
    """Resolve provider branding and the other participants without remote requests."""
    provider = IM_PROVIDER_REGISTRY.get(
        conversation.connection.provider if conversation.connection_id else "internal"
    )
    others = [
        p
        for p in conversation.participants.all()
        if p.user_id != user_id and p.left_at is None
    ]
    person = others[0] if len(others) == 1 else None
    name = (
        conversation.name
        or ", ".join(participant_label(p) for p in others)
        or _("Conversation")
    )
    address = ""
    avatar = ""
    if person and conversation.kind == "direct":
        if person.user_id:
            address = person.user.email or person.user.get_username()
            avatar = person.user.avatar.url if person.user.avatar else ""
        else:
            address = person.identity.address
            avatar = person.identity.avatar_url
    if (
        avatar
        and not (avatar.startswith("/") and not avatar.startswith("//"))
        and urlsplit(avatar).scheme not in ("http", "https")
    ):
        avatar = ""
    resolved = (
        provider.resolve_identity(
            {"name": name, "avatar": avatar, provider.address_field: address}
        )
        if provider
        else {"displayName": name, "avatar": avatar, "address": address}
    )
    return {
        **resolved,
        "initials": "".join(part[0] for part in name.split()[:2]),
        "provider": provider,
        "group": conversation.kind != "direct",
    }
