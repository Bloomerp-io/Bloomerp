"""Call invitations and participant identities, separate from calendar RSVPs."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ConferenceModel


class ConferenceParticipant(ConferenceModel):
    """Retain invited or admitted people even when they never connect."""

    class Role(models.TextChoices):
        HOST = "host", _("Host")
        PARTICIPANT = "participant", _("Participant")

    class InvitationStatus(models.TextChoices):
        INVITED = "invited", _("Invited")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        MISSED = "missed", _("Missed")
        CANCELLED = "cancelled", _("Cancelled")

    immutable_fields = ("session_id", "user_id")
    session = models.ForeignKey(
        "bloomerp.ConferenceSession",
        on_delete=models.PROTECT,
        related_name="participants",
        verbose_name=_("Session"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conference_participations",
        verbose_name=_("User"),
    )
    display_name_snapshot = models.CharField(_("Display name"), max_length=255)
    role = models.CharField(
        _("Role"), max_length=16, choices=Role.choices, default=Role.PARTICIPANT
    )
    invitation_status = models.CharField(
        _("Invitation status"),
        max_length=16,
        choices=InvitationStatus.choices,
        default=InvitationStatus.INVITED,
    )
    invited_at = models.DateTimeField(_("Invited at"), null=True, blank=True)
    responded_at = models.DateTimeField(_("Responded at"), null=True, blank=True)

    class Meta(ConferenceModel.Meta):
        verbose_name = _("Conference participant")
        verbose_name_plural = _("Conference participants")
        constraints = (
            models.UniqueConstraint(
                fields=["session", "user"],
                condition=models.Q(user__isnull=False),
                name="conference_session_user_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(responded_at__isnull=True)
                | models.Q(invited_at__isnull=True)
                | models.Q(responded_at__gte=models.F("invited_at")),
                name="conference_invitation_time_order",
            ),
        )

    def __str__(self) -> str:
        """Retain a useful label after the corresponding user has been deleted."""
        return self.display_name_snapshot
