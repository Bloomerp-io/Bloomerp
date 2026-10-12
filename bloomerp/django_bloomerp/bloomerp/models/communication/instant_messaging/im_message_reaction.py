"""Provider-neutral messaging persistence."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMMessageReaction(IMModel):
    """Store one participant's Unicode emoji or provider custom-emoji reaction."""

    immutable_fields = ("message_id", "participant_id", "emoji")
    message = models.ForeignKey(
        "bloomerp.IMMessage", on_delete=models.CASCADE, related_name="reactions"
    )
    participant = models.ForeignKey(
        "bloomerp.IMConversationParticipant",
        on_delete=models.RESTRICT,
        related_name="reactions",
    )
    emoji = models.CharField(
        max_length=128,
        help_text=_(
            "Unicode emoji, including skin tones/ZWJ sequences, or a provider custom emoji key."
        ),
    )
    provider_reaction_id = models.CharField(max_length=255, blank=True)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_reaction"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "participant", "emoji"], name="im_reaction_unique"
            )
        ]

    def clean(self) -> None:
        """Validate the actor's conversation and reject empty reaction keys."""
        super().clean()
        if not self.emoji.strip():
            raise ValidationError({"emoji": _("An emoji is required.")})
        self.emoji = self.emoji.strip()
        if self.message_id and self.participant_id:
            self.check_conversation(
                "participant",
                self.participant.conversation_id,
                self.message.conversation_id,
            )
