"""Native messaging transport using committed-message invalidation events."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from ..definition import (
    BaseIMAdapter,
    IMCapabilities,
    IMConnectionValidation,
    IMDeliveryResult,
    IMIdentityData,
    IMOutboundMessage,
    IMProviderDefinition,
    IMRecipientPage,
)


class InternalIMAdapter(BaseIMAdapter):
    """Notify authorized user groups; persistence remains in the messaging service."""

    provider_key = "internal"

    def validate_connection(self) -> IMConnectionValidation:
        """Check local channel-layer configuration without claiming client delivery."""
        available = get_channel_layer() is not None
        return IMConnectionValidation(
            valid=available,
            capabilities=IMCapabilities(
                groups=True,
                create_groups=True,
                quoted_replies=True,
                threads=True,
                directory="staff",
            )
            if available
            else IMCapabilities(),
            issues=() if available else ("No Django channel layer is configured.",),
            account_display_name="Bloomerp",
        )

    def discover_recipients(
        self, query: str, *, cursor: str | None = None, limit: int = 25
    ) -> IMRecipientPage:
        """Let active staff discover other active staff independently of user policies.

        Expose only recipient IDs and display labels for the messaging directory.
        """
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        actor = (
            user_model.objects.filter(pk=self.context.actor_id, is_active=True).first()
            if self.context.actor_id
            else None
        )
        if actor is None or not actor.is_staff:
            return IMRecipientPage()
        offset = int(cursor or 0)
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError("Invalid recipient page.")
        users = (
            user_model.objects.filter(
                is_active=True,
                is_staff=True,
                **{f"{user_model.USERNAME_FIELD}__icontains": query},
            )
            .exclude(pk=actor.pk)
            .order_by(user_model.USERNAME_FIELD, "pk")
        )
        page = list(users[offset : offset + limit + 1])
        return IMRecipientPage(
            items=tuple(
                IMIdentityData(external_id=str(user.pk), display_name=str(user))
                for user in page[:limit]
            ),
            next_cursor=str(offset + limit) if len(page) > limit else None,
        )

    def send_message(self, message: IMOutboundMessage) -> IMDeliveryResult:
        """Publish an ID-only update after commit, never re-enter message creation.

        Consumers re-fetch through authorized endpoints. Duplicate notifications
        are harmless; recipients are precomputed by the service, not the browser.
        Channel-layer acceptance does not confirm receipt by any browser.
        """
        layer = get_channel_layer()
        if layer is None:
            raise RuntimeError("No Django channel layer is configured.")
        for user_id in sorted(set(message.recipient_user_ids)):
            async_to_sync(layer.group_send)(
                f"user_{user_id}",
                {
                    "type": "notify",
                    "payload": {
                        "action": "im.message.created",
                        "conversation_id": message.conversation_id,
                        "message_id": message.message_id,
                    },
                },
            )
        return IMDeliveryResult()


INTERNAL_IM_PROVIDER = IMProviderDefinition(
    key="internal",
    display_name="Bloomerp",
    icon="fa-solid fa-comment-dots",
    address_field="email",
    adapter_class=InternalIMAdapter,
    description="Native staff conversations, groups, quotes and threads.",
    planned_capabilities=IMCapabilities(
        groups=True,
        create_groups=True,
        quoted_replies=True,
        threads=True,
        directory="staff",
    ),
    internal=True,
    transport_ready=True,
)
