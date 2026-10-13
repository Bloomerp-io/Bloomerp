"""Provider-neutral messaging persistence."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMMessage(IMModel):
    """Persist an ordered message with independent quoted-reply and thread links."""

    immutable_fields = (
        "conversation_id",
        "sender_id",
        "sequence",
        "reply_to_id",
        "thread_root_id",
        "client_id",
    )
    conversation = models.ForeignKey(
        "bloomerp.IMConversation", on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        "bloomerp.IMConversationParticipant",
        on_delete=models.RESTRICT,
        related_name="messages",
    )
    sequence = models.PositiveBigIntegerField(
        help_text=_("Allocated under a conversation lock by the messaging service.")
    )
    body = models.TextField(blank=True)
    body_html = models.TextField(
        blank=True,
        help_text=_("Sanitized editor HTML; body contains the searchable text."),
    )
    direction = models.CharField(
        max_length=16,
        choices=[
            ("internal", _("Internal")),
            ("inbound", _("Inbound")),
            ("outbound", _("Outbound")),
        ],
        default="internal",
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("pending", _("Pending")),
            ("accepted", _("Accepted")),
            ("sent", _("Sent")),
            ("delivered", _("Delivered")),
            ("read", _("Read")),
            ("failed", _("Failed")),
        ],
        default="pending",
    )
    client_id = models.CharField(max_length=255, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="quoted_replies",
    )
    thread_root = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="thread_replies",
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_message"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"], name="im_message_sequence_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1), name="im_message_sequence_positive"
            ),
            models.UniqueConstraint(
                fields=["conversation", "sender", "client_id"],
                condition=~models.Q(client_id=""),
                name="im_message_client_unique",
            ),
            models.UniqueConstraint(
                fields=["conversation", "provider_message_id"],
                condition=~models.Q(provider_message_id=""),
                name="im_message_provider_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(reply_to=models.F("pk")),
                name="im_message_no_self_quote",
            ),
            models.CheckConstraint(
                condition=~models.Q(thread_root=models.F("pk")),
                name="im_message_no_self_thread",
            ),
        ]
        indexes = [
            models.Index(
                fields=["conversation", "thread_root", "sequence"],
                name="im_message_thread_idx",
            )
        ]

    def clean(self) -> None:
        """Validate sender membership and earlier same-conversation message links."""
        super().clean()
        if self.sender_id:
            self.check_conversation(
                "sender", self.sender.conversation_id, self.conversation_id
            )
        for field in ("reply_to", "thread_root"):
            if getattr(self, f"{field}_id"):
                reference = getattr(self, field)
                self.check_conversation(
                    field, reference.conversation_id, self.conversation_id
                )
                if reference.pk == self.pk or reference.sequence >= self.sequence:
                    raise ValidationError(
                        {field: _("Reference an earlier message in this conversation.")}
                    )
                if field == "thread_root" and reference.thread_root_id:
                    raise ValidationError(
                        {
                            field: _(
                                "Threads must reference a root message, not another reply."
                            )
                        }
                    )
