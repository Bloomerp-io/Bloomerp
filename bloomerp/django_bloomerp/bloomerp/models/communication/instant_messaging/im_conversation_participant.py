"""Provider-neutral messaging persistence."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMConversationParticipant(IMModel):
    """Track either a staff user or external identity and their personal read state."""

    immutable_fields = ("conversation_id", "user_id", "identity_id")
    conversation = models.ForeignKey(
        "bloomerp.IMConversation", on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="im_participations",
    )
    identity = models.ForeignKey(
        "bloomerp.IMIdentity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="participations",
    )
    role = models.CharField(
        max_length=16,
        choices=[("member", _("Member")), ("admin", _("Admin")), ("owner", _("Owner"))],
        default="member",
    )
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    muted_until = models.DateTimeField(null=True, blank=True)
    last_read_message = models.ForeignKey(
        "bloomerp.IMMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_participant"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(user__isnull=False, identity__isnull=True)
                | models.Q(user__isnull=True, identity__isnull=False),
                name="im_participant_one_identity",
            ),
            models.UniqueConstraint(
                fields=["conversation", "user"],
                condition=models.Q(user__isnull=False),
                name="im_participant_user_unique",
            ),
            models.UniqueConstraint(
                fields=["conversation", "identity"],
                condition=models.Q(identity__isnull=False),
                name="im_participant_identity_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(left_at__isnull=True)
                | models.Q(left_at__gte=models.F("joined_at")),
                name="im_participant_dates",
            ),
        ]

    def clean(self) -> None:
        """Keep external identities and read markers inside their account/conversation."""
        super().clean()
        if (
            self.identity_id
            and self.identity.connection_id != self.conversation.connection_id
        ):
            raise ValidationError(
                {"identity": _("Identity belongs to another connection.")}
            )
        if self.last_read_message_id:
            self.check_conversation(
                "last_read_message",
                self.last_read_message.conversation_id,
                self.conversation_id,
            )
            if self.last_read_message.thread_root_id:
                raise ValidationError(
                    {"last_read_message": _("Track thread reads separately.")}
                )
