"""Provider-neutral messaging persistence."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMThreadReadPosition(IMModel):
    """Track a participant's thread reads separately from the main conversation."""

    immutable_fields = ("participant_id", "thread_root_id")
    participant = models.ForeignKey(
        "bloomerp.IMConversationParticipant",
        on_delete=models.CASCADE,
        related_name="thread_read_positions",
    )
    thread_root = models.ForeignKey(
        "bloomerp.IMMessage", on_delete=models.CASCADE, related_name="read_positions"
    )
    last_read_message = models.ForeignKey(
        "bloomerp.IMMessage", on_delete=models.CASCADE, related_name="+"
    )

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_thread_read"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "thread_root"], name="im_thread_read_unique"
            )
        ]

    def clean(self) -> None:
        """Require a real root and a read marker inside that participant's thread."""
        super().clean()
        if self.participant_id and self.thread_root_id and self.last_read_message_id:
            self.check_conversation(
                "thread_root",
                self.thread_root.conversation_id,
                self.participant.conversation_id,
            )
            if self.thread_root.thread_root_id:
                raise ValidationError({"thread_root": _("Select a root message.")})
            if (
                self.last_read_message_id != self.thread_root_id
                and self.last_read_message.thread_root_id != self.thread_root_id
            ):
                raise ValidationError(
                    {
                        "last_read_message": _(
                            "The read marker must belong to this thread."
                        )
                    }
                )
