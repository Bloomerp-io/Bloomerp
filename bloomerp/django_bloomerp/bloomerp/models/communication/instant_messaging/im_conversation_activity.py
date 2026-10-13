"""Generic conversation activity projections for calls and future session types."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from .base import IMModel


class IMConversationActivity(IMModel):
    """Index an independently stored activity for ordering, inbox previews and read state."""

    conversation = models.ForeignKey(
        "bloomerp.IMConversation",
        verbose_name=_("Conversation"),
        on_delete=models.CASCADE,
        related_name="activities",
    )
    kind = models.CharField(_("Activity type"), max_length=64)
    source_id = models.CharField(_("Source identifier"), max_length=255)
    summary = models.CharField(_("Summary"), max_length=500)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Actor"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="im_activities",
    )

    class Meta(IMModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "kind", "source_id"],
                name="im_activity_source_unique",
            )
        ]

    def __str__(self) -> str:
        """Return the short activity summary without loading its source record."""
        return self.summary
