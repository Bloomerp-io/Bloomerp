"""Opt-in provider hooks connecting user-backed IM conversations to conferencing."""

from time import sleep
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, connection, transaction
from django.utils.translation import gettext as _
from django.utils.translation import override

from bloomerp.communication.builtins.instant_messaging.access import IMAccessManager
from bloomerp.communication.builtins.instant_messaging.definition import (
    IMCallCapabilities,
)
from bloomerp.config.definition import get_bloomerp_config
from bloomerp.models.communication.conferencing import ConferenceRoom, ConferenceSession
from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationActivity,
)
from bloomerp.models.users.user import AbstractBloomerpUser

from .controller import ConferenceController, session_payload


def participants(
    user: AbstractBloomerpUser, chat: IMConversation
) -> list[AbstractBloomerpUser]:
    """Authorize current active staff members for providers opting into user-backed calls."""
    if not IMAccessManager(user).has_access_to_conversation(chat) or not user.is_staff:
        raise PermissionDenied
    return [
        member.user
        for member in chat.participants.select_related("user").filter(
            left_at__isnull=True, user__is_active=True, user__is_staff=True
        )
    ]


def capabilities(
    user: AbstractBloomerpUser, chat: IMConversation
) -> IMCallCapabilities:
    """Expose media support only when configuration and current membership allow it."""
    if (
        not get_bloomerp_config().conferencing.enabled
        or not user.is_staff
        or not user.is_active
    ):
        return IMCallCapabilities()
    return IMCallCapabilities(audio=True, video=True, groups=True, screen_share=True, share_links=True)


def start(
    user: AbstractBloomerpUser, chat: IMConversation, media_mode: str, client_id: str
) -> dict[str, str]:
    """Reuse a persistent source room and delegate the actual call lifecycle."""
    invitees = participants(user, chat)
    with transaction.atomic():
        IMConversation.objects.select_for_update().get(pk=chat.pk)
        room = (
            chat.conference_rooms.filter(archived=False)
            .order_by("datetime_created")
            .first()
        )
        if room is None:
            room = ConferenceRoom.objects.create(
                title=chat.name or _("Conversation call"),
                conversation=chat,
                created_by=user,
            )
    session = ConferenceController(user).start(room, invitees, media_mode, client_id)
    return {**session_payload(session), "can_end": "true"}


def timeline(
    user: AbstractBloomerpUser, chat: IMConversation
) -> list[ConferenceSession]:
    """Project only the actor's invited sessions in an accessible conversation."""
    if not IMAccessManager(user).has_access_to_conversation(chat):
        return []
    return list(
        ConferenceSession.objects.filter(
            room__conversation=chat, participants__user=user
        ).order_by("datetime_created")
    )


def project_session(session: ConferenceSession) -> None:
    """Update one IM activity and invalidate its source conversation after commit."""
    from bloomerp.communication.builtins.instant_messaging.controller import (
        IMController,
    )
    from bloomerp.communication.builtins.instant_messaging.inbox_source import (
        publish_conversation_activity,
    )

    chat = session.room.conversation
    if chat is None:
        return
    # Retry the entire transaction: SQLite cannot upgrade a stale read snapshot
    # after a webhook or another request has acquired the write lock.
    for attempt in range(4):
        try:
            changed = store_session_activity(session.pk)
            break
        except OperationalError as error:
            if (
                connection.vendor != "sqlite"
                or not any(
                    reason in str(error).lower()
                    for reason in (
                        "database is locked",
                        "database table is locked",
                    )
                )
                or attempt == 3
            ):
                raise
            sleep(0.05 * (2**attempt))
    IMController.notify_reactions(chat.pk)
    publish_conversation_activity(chat.pk, notify=changed)


def store_session_activity(session_id: UUID) -> bool:
    """Project fresh state atomically and report whether an inbox alert is new."""
    with transaction.atomic():
        session = ConferenceSession.objects.select_related("room__conversation").get(
            pk=session_id
        )
        chat = session.room.conversation
        if chat is None:
            return False
        chat = IMConversation.objects.select_for_update().get(pk=chat.pk)
        session.refresh_from_db()
        # A request and a webhook may use different active languages. Persist a
        # stable summary so locale changes cannot manufacture a new activity.
        with override(settings.LANGUAGE_CODE):
            summary = _("Conference call: %(status)s") % {
                "status": session.get_status_display()
            }
        activity, created = IMConversationActivity.objects.get_or_create(
            conversation=chat,
            kind="conference_call",
            source_id=str(session.pk),
            defaults={"summary": summary, "actor_id": session.created_by_id},
        )
        changed = created or activity.summary != summary
        if not created and changed:
            activity.summary = summary
            activity.save(update_fields=["summary", "datetime_updated"])
        if (
            chat.last_activity_at is None
            or chat.last_activity_at < session.datetime_updated
        ):
            chat.last_activity_at = session.datetime_updated
            chat.save(update_fields=["last_activity_at"])
        return changed
