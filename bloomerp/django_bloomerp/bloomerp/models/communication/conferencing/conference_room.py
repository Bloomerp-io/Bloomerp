"""Persistent conferencing spaces that may optionally originate in IM."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ConferenceModel


class ConferenceRoom(ConferenceModel):
    """Provide a stable application identity across calls and future calendar events."""

    title = models.CharField(_("Title"), max_length=255)
    conversation = models.ForeignKey(
        "bloomerp.IMConversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conference_rooms",
        verbose_name=_("Conversation"),
    )
    archived = models.BooleanField(_("Archived"), default=False)

    class Meta(ConferenceModel.Meta):
        verbose_name = _("Conference room")
        verbose_name_plural = _("Conference rooms")

    def __str__(self) -> str:
        """Describe a room without requiring its optional IM context."""
        return self.title
