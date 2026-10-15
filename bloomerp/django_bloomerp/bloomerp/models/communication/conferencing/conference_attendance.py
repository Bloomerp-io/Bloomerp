"""Actual connections, distinct from invitations and scheduled attendance."""

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ConferenceModel


def new_livekit_identity() -> str:
    """Generate a distinct identity for each device or subsequent attendance."""
    return f"attendance-{uuid4().hex}"


class ConferenceAttendance(ConferenceModel):
    """Track one connection interval; reconnects retaining a SID reuse the record."""

    immutable_fields = ("participant_id", "livekit_identity")
    participant = models.ForeignKey(
        "bloomerp.ConferenceParticipant",
        on_delete=models.PROTECT,
        related_name="attendances",
        verbose_name=_("Participant"),
    )
    livekit_identity = models.CharField(
        _("LiveKit identity"),
        max_length=255,
        default=new_livekit_identity,
        editable=False,
    )
    livekit_participant_sid = models.CharField(
        _("LiveKit participant SID"), max_length=255, blank=True
    )
    joined_at = models.DateTimeField(_("Joined at"))
    left_at = models.DateTimeField(_("Left at"), null=True, blank=True)
    leave_reason = models.CharField(_("Leave reason"), max_length=255, blank=True)

    class Meta(ConferenceModel.Meta):
        verbose_name = _("Conference attendance")
        verbose_name_plural = _("Conference attendances")
        constraints = (
            models.CheckConstraint(
                condition=models.Q(left_at__isnull=True)
                | models.Q(left_at__gte=models.F("joined_at")),
                name="conference_attendance_time_order",
            ),
            models.UniqueConstraint(
                fields=["livekit_participant_sid"],
                condition=~models.Q(livekit_participant_sid=""),
                name="conference_attendance_sid_unique",
            ),
        )

    def validate_previous(self, previous: "ConferenceAttendance") -> None:
        """Keep provider sessions stable and closed attendance intervals closed."""
        super().validate_previous(previous)
        if (
            previous.livekit_participant_sid
            and previous.livekit_participant_sid != self.livekit_participant_sid
        ):
            raise ValidationError(
                {
                    "livekit_participant_sid": _(
                        "The participant SID is immutable once assigned."
                    )
                }
            )
        if previous.left_at is not None and self.left_at is None:
            raise ValidationError(
                {"left_at": _("A closed attendance cannot be reopened.")}
            )

    def __str__(self) -> str:
        """Identify a connection without loading participant or user records."""
        return self.livekit_identity
