"""Individual call occurrences within a persistent conference room."""

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ConferenceModel


def new_livekit_room_name() -> str:
    """Generate an opaque provider room name that is never reused by later calls."""
    return f"conference-{uuid4().hex}"


class ConferenceSession(ConferenceModel):
    """Retain the lifecycle of one call independently of its temporary LiveKit room."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        RINGING = "ringing", _("Ringing")
        ACTIVE = "active", _("Active")
        ENDED = "ended", _("Ended")
        CANCELLED = "cancelled", _("Cancelled")
        FAILED = "failed", _("Failed")

    class MediaMode(models.TextChoices):
        AUDIO = "audio", _("Audio")
        VIDEO = "video", _("Video")

    immutable_fields = (
        "room_id",
        "livekit_room_name",
        "initial_media_mode",
        "client_id",
    )
    room = models.ForeignKey(
        "bloomerp.ConferenceRoom",
        on_delete=models.PROTECT,
        related_name="sessions",
        verbose_name=_("Room"),
    )
    livekit_room_name = models.CharField(
        _("LiveKit room name"),
        max_length=255,
        unique=True,
        default=new_livekit_room_name,
        editable=False,
    )
    share_token = models.UUIDField(default=uuid4, unique=True, editable=False)
    livekit_room_sid = models.CharField(
        _("LiveKit room SID"), max_length=255, blank=True
    )
    initial_media_mode = models.CharField(
        _("Initial media mode"),
        max_length=10,
        choices=MediaMode.choices,
        default=MediaMode.VIDEO,
    )
    status = models.CharField(
        _("Status"), max_length=16, choices=Status.choices, default=Status.PENDING
    )
    client_id = models.CharField(_("Client request ID"), max_length=255, blank=True)
    started_at = models.DateTimeField(_("Started at"), null=True, blank=True)
    ended_at = models.DateTimeField(_("Ended at"), null=True, blank=True)
    end_reason = models.CharField(_("End reason"), max_length=255, blank=True)

    class Meta(ConferenceModel.Meta):
        verbose_name = _("Conference session")
        verbose_name_plural = _("Conference sessions")
        constraints = (
            models.UniqueConstraint(
                fields=["room", "client_id"],
                condition=~models.Q(client_id=""),
                name="conference_request_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(started_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="conference_session_time_order",
            ),
            models.UniqueConstraint(
                fields=["livekit_room_sid"],
                condition=~models.Q(livekit_room_sid=""),
                name="conference_session_sid_unique",
            ),
            models.UniqueConstraint(
                fields=["room"],
                condition=models.Q(status__in=["pending", "ringing", "active"]),
                name="conference_room_open_session",
            ),
        )

    def clean(self) -> None:
        """Require timestamps consistent with the session's current lifecycle."""
        super().clean()
        terminal = self.status in {
            self.Status.ENDED,
            self.Status.CANCELLED,
            self.Status.FAILED,
        }
        if terminal != (self.ended_at is not None):
            raise ValidationError(
                {"ended_at": _("Only finished sessions must have an end time.")}
            )
        if (
            self.status in {self.Status.ACTIVE, self.Status.ENDED}
            and self.started_at is None
        ):
            raise ValidationError(
                {"started_at": _("An active or ended call must have a start time.")}
            )
        if self._state.adding and self.room_id and self.room.archived:
            raise ValidationError(
                {"room": _("Archived rooms cannot start new sessions.")}
            )

    def validate_previous(self, previous: "ConferenceSession") -> None:
        """Prevent late events from reopening or moving a call backwards."""
        super().validate_previous(previous)
        allowed = {
            self.Status.PENDING: {
                self.Status.PENDING,
                self.Status.RINGING,
                self.Status.ACTIVE,
                self.Status.ENDED,
                self.Status.CANCELLED,
                self.Status.FAILED,
            },
            self.Status.RINGING: {
                self.Status.RINGING,
                self.Status.ACTIVE,
                self.Status.ENDED,
                self.Status.CANCELLED,
                self.Status.FAILED,
            },
            self.Status.ACTIVE: {
                self.Status.ACTIVE,
                self.Status.ENDED,
                self.Status.FAILED,
            },
        }
        if self.status not in allowed.get(previous.status, {previous.status}):
            raise ValidationError(
                {"status": _("The session cannot return to an earlier state.")}
            )
        if (
            previous.livekit_room_sid
            and previous.livekit_room_sid != self.livekit_room_sid
        ):
            raise ValidationError(
                {
                    "livekit_room_sid": _(
                        "The LiveKit room SID is immutable once assigned."
                    )
                }
            )

    def __str__(self) -> str:
        """Describe the call without querying its parent room."""
        return f"{self.livekit_room_name} ({self.status})"
