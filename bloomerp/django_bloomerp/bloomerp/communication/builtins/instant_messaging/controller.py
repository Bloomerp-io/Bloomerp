"""Coordinate permission-checked recipient discovery and conversation creation."""

import logging
from functools import partial
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone

from bloomerp.models.communication.instant_messaging import (
    IMConversation,
    IMConversationParticipant,
    IMMessage,
    IMMessageReaction,
    IMThreadReadPosition,
)
from bloomerp.models.users.user import AbstractBloomerpUser

from .access import IMAccessManager
from .content import prepare_content
from .definition import IMConnectionContext, IMOutboundMessage, IMRecipientPage
from .registry import IM_PROVIDER_REGISTRY

REACTION_EMOJIS = (
    "👍",
    "👎",
    "❤️",
    "😂",
    "🎉",
    "😮",
    "😢",
    "🙏",
    "🔥",
    "👀",
    "✅",
    "🚀",
    "💯",
    "🤔",
    "👏",
    "😊",
)


class IMController:
    """Own messaging persistence while providers discover and transport recipients."""

    def __init__(self, user: AbstractBloomerpUser) -> None:
        """Bind operations to the authenticated requester."""
        self.user = user

    def discover_recipients(
        self, query: str, cursor: str | None = None
    ) -> IMRecipientPage:
        """Resolve the built-in directory without provisioning a connection."""
        provider = IM_PROVIDER_REGISTRY.get("internal")
        adapter = provider.create_adapter(
            IMConnectionContext(
                connection_id=None, provider=provider.key, actor_id=str(self.user.pk)
            )
        )
        return adapter.discover_recipients(query, cursor=cursor)

    @transaction.atomic
    def start_internal_conversation(self, recipient_id: str) -> IMConversation:
        """Require active staff on both sides and reuse an exact two-person chat."""
        if (
            not self.user.is_authenticated
            or not self.user.is_active
            or not self.user.is_staff
        ):
            raise PermissionDenied
        user_model = get_user_model()
        recipient = (
            user_model.objects.filter(pk=recipient_id, is_active=True, is_staff=True)
            .exclude(pk=self.user.pk)
            .first()
        )
        if recipient is None:
            raise PermissionDenied
        conversations = (
            IMConversation.objects.filter(connection__isnull=True, kind="direct")
            .annotate(member_count=Count("participants"))
            .filter(member_count=2)
        )
        conversations = conversations.filter(
            participants__user=self.user, participants__left_at__isnull=True
        ).filter(participants__user=recipient, participants__left_at__isnull=True)
        existing = conversations.first()
        if existing:
            return existing
        conversation = IMConversation.objects.create(kind="direct")
        IMConversationParticipant.objects.create(
            conversation=conversation, user=self.user
        )
        IMConversationParticipant.objects.create(
            conversation=conversation, user=recipient
        )
        return conversation

    @transaction.atomic
    def create_internal_group(
        self, name: str, recipient_ids: list[str]
    ) -> IMConversation:
        """Create a named native group with an owner and selected active staff."""
        if (
            not self.user.is_authenticated
            or not self.user.is_active
            or not self.user.is_staff
        ):
            raise PermissionDenied
        name = name.strip()
        if not name or len(name) > 255:
            raise ValidationError("Enter a group name of up to 255 characters.")
        ids = set(recipient_ids) - {str(self.user.pk)}
        users = list(
            get_user_model().objects.filter(pk__in=ids, is_active=True, is_staff=True)
        )
        if len(users) != len(ids):
            raise ValidationError("Select active staff users.")
        if not users:
            raise ValidationError("Select at least one other participant.")
        chat = IMConversation.objects.create(kind="group", name=name)
        IMConversationParticipant.objects.create(
            conversation=chat, user=self.user, role="owner"
        )
        for user in users:
            IMConversationParticipant.objects.create(conversation=chat, user=user)
        transaction.on_commit(partial(self.notify_group, chat.pk))
        return chat

    @transaction.atomic
    def update_internal_group(
        self, conversation_id: UUID, action: str, *, user_id: str = "", name: str = ""
    ) -> IMConversation:
        """Enforce native group membership and role changes under one conversation lock."""
        chat = (
            IMAccessManager(self.user)
            .get_conversations()
            .select_for_update()
            .filter(pk=conversation_id, kind="group", connection__isnull=True)
            .first()
        )
        if chat is None or not self.user.is_staff:
            raise PermissionDenied
        if chat.status == "archived":
            raise ValidationError("This group is archived.")
        actor = chat.participants.get(user=self.user, left_at__isnull=True)
        recipients = tuple(
            chat.participants.filter(left_at__isnull=True).values_list(
                "user_id", flat=True
            )
        )
        if action == "leave":
            if actor.role == "owner":
                raise ValidationError("Transfer ownership before leaving the group.")
            actor.left_at = timezone.now()
            actor.save(update_fields=["left_at"])
        else:
            if actor.role not in {"owner", "admin"}:
                raise PermissionDenied
            if action == "rename":
                name = name.strip()
                if not name or len(name) > 255:
                    raise ValidationError("Enter a group name of up to 255 characters.")
                chat.name = name
                chat.save(update_fields=["name"])
            elif action == "add":
                user = (
                    get_user_model()
                    .objects.filter(pk=user_id, is_active=True, is_staff=True)
                    .first()
                )
                if user is None:
                    raise ValidationError("Select an active staff user.")
                member, created = chat.participants.get_or_create(user=user)
                if not created and member.left_at:
                    member.left_at = None
                    member.role = "member"
                    member.joined_at = timezone.now()
                    member.save(update_fields=["left_at", "role", "joined_at"])
            elif action in {"remove", "promote", "demote", "transfer"}:
                member = chat.participants.filter(
                    user_id=user_id, left_at__isnull=True
                ).first()
                if member is None:
                    raise ValidationError("Participant is unavailable.")
                if member.pk == actor.pk or member.role == "owner":
                    raise ValidationError("Use leave or transfer ownership instead.")
                if actor.role != "owner" and (
                    action != "remove" or member.role != "member"
                ):
                    raise PermissionDenied
                if action == "remove":
                    member.left_at = timezone.now()
                    member.save(update_fields=["left_at"])
                else:
                    if action == "transfer":
                        actor.role = "admin"
                        actor.save(update_fields=["role"])
                    member.role = {
                        "promote": "admin",
                        "demote": "member",
                        "transfer": "owner",
                    }[action]
                    member.save(update_fields=["role"])
            else:
                raise ValidationError("Unknown group action.")
        transaction.on_commit(partial(self.notify_group, chat.pk, recipients))
        return chat

    def notify_group(
        self, conversation_id: UUID, previous_user_ids: tuple[int, ...] = ()
    ) -> None:
        """Invalidate group membership for current and removed participants after commit."""
        from bloomerp.utils.realtime import send_user_message

        from .inbox_source import publish_conversation_activity

        current_users = set(
            IMConversationParticipant.objects.filter(
                conversation_id=conversation_id,
                left_at__isnull=True,
                user__is_active=True,
            ).values_list("user_id", flat=True)
        )
        from bloomerp.models.communication.inbox.inbox import Inbox
        from bloomerp.models.communication.inbox.inbox_item import InboxItem

        InboxItem.objects.filter(
            item_type="instant_messaging_item",
            related_item_id=str(conversation_id),
            folder__inbox__user_id__in=set(previous_user_ids) - current_users,
        ).delete()
        try:
            publish_conversation_activity(conversation_id, notify=False)
        except Exception:
            logging.getLogger(__name__).exception(
                "IM group inbox update failed for %s", conversation_id
            )
        try:
            for user_id in set(previous_user_ids) | current_users:
                send_user_message(
                    user_id,
                    {
                        "action": "im.group.updated",
                        "conversation_id": str(conversation_id),
                        "notification_count": Inbox.get_unread_count_for_user(user_id),
                    },
                )
        except Exception:
            logging.getLogger(__name__).exception(
                "IM group notification failed for %s", conversation_id
            )

    @transaction.atomic
    def send_message(
        self,
        conversation_id: UUID,
        html: str,
        client_id: str,
        *,
        reply_to_id: str | None = None,
        thread_root_id: str | None = None,
    ) -> IMMessage:
        """Persist one validated native send under a lock, deduplicating client retries."""
        if not client_id or len(client_id) > 255:
            raise ValidationError("A client message ID is required.")
        chat = (
            IMAccessManager(self.user)
            .get_conversations()
            .select_for_update()
            .filter(pk=conversation_id)
            .first()
        )
        if chat is None:
            raise PermissionDenied
        if chat.connection_id:
            raise ValidationError(
                "Sending through this external provider is not available yet."
            )
        if chat.status == "archived":
            raise ValidationError("This conversation is archived.")
        member = chat.participants.get(user=self.user, left_at__isnull=True)
        existing = chat.messages.filter(sender=member, client_id=client_id).first()
        if existing:
            return existing
        body_html, body = prepare_content(html, self.user, chat)
        references: dict[str, IMMessage | None] = {}
        for field, value in [
            ("reply_to", reply_to_id),
            ("thread_root", thread_root_id),
        ]:
            reference = (
                chat.messages.filter(pk=value, deleted_at__isnull=True).first()
                if value
                else None
            )
            if value and reference is None:
                raise ValidationError("Referenced message is unavailable.")
            references[field] = reference
        sequence = (chat.messages.aggregate(last=Max("sequence"))["last"] or 0) + 1
        message = IMMessage.objects.create(
            conversation=chat,
            sender=member,
            sequence=sequence,
            body=body,
            body_html=body_html,
            client_id=client_id,
            status="sent",
            sent_at=timezone.now(),
            **references,
        )
        chat.last_activity_at = message.sent_at
        chat.save(update_fields=["last_activity_at"])
        transaction.on_commit(partial(self.notify_message, message.pk))
        return message

    def notify_message(self, message_id: UUID) -> None:
        """Publish committed-message invalidation without turning notification errors into failed sends."""
        message = IMMessage.objects.select_related("conversation", "sender").get(
            pk=message_id
        )
        from .inbox_source import publish_conversation_activity

        try:
            publish_conversation_activity(message.conversation_id)
        except Exception:
            logging.getLogger(__name__).exception(
                "IM inbox update failed for %s", message.pk
            )
        recipients = tuple(
            str(pk)
            for pk in message.conversation.participants.filter(
                left_at__isnull=True, user__is_active=True
            ).values_list("user_id", flat=True)
        )
        adapter = IM_PROVIDER_REGISTRY.get("internal").create_adapter(
            IMConnectionContext(None, "internal")
        )
        try:
            adapter.send_message(
                IMOutboundMessage(
                    str(message.pk),
                    str(message.conversation_id),
                    message.client_id,
                    str(message.sender_id),
                    message.body,
                    recipient_user_ids=recipients,
                    body_html=message.body_html,
                )
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "IM message notification failed for %s", message.pk
            )

    @transaction.atomic
    def set_reaction(
        self, conversation_id: UUID, message_id: UUID, emoji: str, active: bool
    ) -> None:
        """Idempotently add or remove the requester's reaction after rechecking access."""
        chat = (
            IMAccessManager(self.user)
            .get_conversations()
            .select_for_update()
            .filter(pk=conversation_id)
            .first()
        )
        if chat is None:
            raise PermissionDenied
        if chat.connection_id or chat.status == "archived":
            raise ValidationError("Reactions are unavailable for this conversation.")
        if emoji not in REACTION_EMOJIS:
            raise ValidationError("Choose an emoji from the reaction picker.")
        message = chat.messages.filter(pk=message_id, deleted_at__isnull=True).first()
        if message is None:
            raise ValidationError("Message is unavailable.")
        member = chat.participants.get(user=self.user, left_at__isnull=True)
        reactions = IMMessageReaction.objects.filter(
            message=message, participant=member, emoji=emoji
        )
        changed = False
        if active:
            if not reactions.exists():
                IMMessageReaction.objects.create(
                    message=message, participant=member, emoji=emoji
                )
                changed = True
        else:
            changed = reactions.delete()[0] > 0
        if changed:
            transaction.on_commit(partial(self.notify_reactions, chat.pk))

    def notify_reactions(self, conversation_id: UUID) -> None:
        """Publish content-free reaction invalidations only after persistence commits."""
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        try:
            layer = get_channel_layer()
            if layer is None:
                return
            recipients = IMConversationParticipant.objects.filter(
                conversation_id=conversation_id,
                left_at__isnull=True,
                user__is_active=True,
            ).values_list("user_id", flat=True)
            for user_id in recipients:
                async_to_sync(layer.group_send)(
                    f"user_{user_id}",
                    {
                        "type": "notify",
                        "payload": {
                            "action": "im.reactions.updated",
                            "conversation_id": str(conversation_id),
                        },
                    },
                )
        except Exception:
            logging.getLogger(__name__).exception(
                "IM reaction notification failed for %s", conversation_id
            )

    @transaction.atomic
    def mark_read(
        self,
        conversation_id: UUID,
        message_id: UUID,
        thread_root_id: UUID | None = None,
    ) -> None:
        """Advance only the caller's read position to a message actually rendered by the client."""
        chat = (
            IMAccessManager(self.user)
            .get_conversations()
            .select_for_update()
            .filter(pk=conversation_id)
            .first()
        )
        if chat is None:
            raise PermissionDenied
        message = chat.messages.filter(pk=message_id).first()
        if message is None:
            raise ValidationError("Message is unavailable.")
        member = chat.participants.select_related("last_read_message").get(
            user=self.user, left_at__isnull=True
        )
        position = member
        if thread_root_id:
            root = chat.messages.filter(
                pk=thread_root_id, thread_root__isnull=True
            ).first()
            if root is None or (
                message.pk != root.pk and message.thread_root_id != root.pk
            ):
                raise ValidationError("Read position is outside this thread.")
            position = (
                IMThreadReadPosition.objects.select_related("last_read_message")
                .filter(participant=member, thread_root=root)
                .first()
            )
            if position is None:
                IMThreadReadPosition.objects.create(
                    participant=member, thread_root=root, last_read_message=message
                )
                return
        elif message.thread_root_id:
            raise ValidationError("Track thread reads separately.")
        if (
            position.last_read_message_id
            and position.last_read_message.sequence >= message.sequence
        ):
            return
        position.last_read_message = message
        position.save(update_fields=["last_read_message"])
        from .inbox_source import sync_conversation_read

        if not thread_root_id:
            sync_conversation_read(chat.pk, self.user.pk)
        transaction.on_commit(self.notify_read_position)

    def notify_read_position(self) -> None:
        """Refresh unread badges in the same user's other browser sessions."""
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        from bloomerp.models.communication.inbox.inbox import Inbox

        try:
            layer = get_channel_layer()
            if layer:
                async_to_sync(layer.group_send)(
                    f"user_{self.user.pk}",
                    {
                        "type": "notify",
                        "payload": {
                            "action": "im.read.updated",
                            "notification_count": Inbox.get_unread_count_for_user(
                                self.user
                            ),
                        },
                    },
                )
        except Exception:
            logging.getLogger(__name__).exception("IM read notification failed")
