"""Provider-dispatched call operations with no provider-key special cases."""

from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError

from bloomerp.models.communication.instant_messaging import IMConversation
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.utils.callables import resolve_hook

from .access import IMAccessManager
from .definition import IMCallCapabilities, IMCallingDefinition
from .registry import IM_PROVIDER_REGISTRY


def calling_definition(chat: IMConversation) -> IMCallingDefinition | None:
    """Resolve calling hooks from the conversation's registered provider."""
    provider = IM_PROVIDER_REGISTRY.get(chat.provider_key)
    return provider.calling if provider else None


def call_capabilities(
    user: AbstractBloomerpUser, chat: IMConversation
) -> IMCallCapabilities:
    """Hide unavailable actions while applying the same access gate as mutations."""
    definition = calling_definition(chat)
    if (
        definition is None
        or chat.status == "archived"
        or not IMAccessManager(user).has_access_to_conversation(chat)
    ):
        return IMCallCapabilities()
    return resolve_hook(definition.capabilities_resolver)(user, chat)


def call_participants(
    user: AbstractBloomerpUser, chat: IMConversation
) -> list[AbstractBloomerpUser]:
    """Resolve current eligible users through the provider's authorization hook."""
    definition = calling_definition(chat)
    if definition is None or not IMAccessManager(user).has_access_to_conversation(chat):
        raise PermissionDenied
    return list(resolve_hook(definition.participants_resolver)(user, chat))


def start_call(
    user: AbstractBloomerpUser, conversation_id: UUID, media_mode: str, client_id: str
) -> dict[str, str]:
    """Dispatch an authorized call through the provider's declared start handler."""
    chat = IMAccessManager(user).get_conversations().filter(pk=conversation_id).first()
    if chat is None:
        raise PermissionDenied
    capabilities = call_capabilities(user, chat)
    if (
        media_mode not in {"audio", "video"}
        or not getattr(capabilities, media_mode)
        or (chat.kind == "group" and not capabilities.groups)
    ):
        raise ValidationError("This conversation does not support the requested call.")
    if not client_id or len(client_id) > 255:
        raise ValidationError("A client request identifier is required.")
    definition = calling_definition(chat)
    return resolve_hook(definition.start_handler)(user, chat, media_mode, client_id)
