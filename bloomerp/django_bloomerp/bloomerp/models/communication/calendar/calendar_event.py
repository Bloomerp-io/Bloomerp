"""Shared meetings with independent calendar placement and organizer identity."""

from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_htmx.http import HttpResponseLocation

from bloomerp.dataviews.calendar.config import CalendarDataView
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DataviewAction,
    DataviewActionContext,
    DataviewHTMLAction,
    DataviewModalAction,
    ModelViewSettings,
    ObjectAction,
    get_default_dataview_actions,
)
from bloomerp.modules.communication import CommunicationModule

from .base import CalendarModel
from .validators import new_calendar_uid, validate_calendar_timezone

if TYPE_CHECKING:
    from bloomerp.models.users.user import AbstractBloomerpUser

    from .calendar_event_participant import CalendarEventParticipant



def back_to_inbox(context: DataviewActionContext) -> HttpResponse:
    """Navigate back to the selected Inbox through an HTMX GET with browser history."""
    return HttpResponseLocation(reverse("inbox"), target="#main-content")


def back_to_inbox_visible(context: DataviewActionContext) -> bool:
    """Show Inbox navigation only when the event dataview is scoped to an Inbox."""
    return bool(
        context.request.GET.get("inboxes")
        or context.request.GET.get("inboxes__in")
        or (
            context.request.GET.get("calendar_color_field") == "inboxes"
            and context.request.GET.get("calendar_color_values")
        )
    )


def calendar_overlay_visible(context: DataviewActionContext) -> bool:
    """Offer overlays only when the calendar's Inbox membership field is readable."""
    from bloomerp.permissions.manager import UserPolicyManager

    manager = UserPolicyManager(context.request.user)
    return (
        context.preference.view_type == "calendar"
        and manager.has_global_permission(context.model, "view")
        and manager.get_accessible_fields(context.model, "view")
        .filter(field="inboxes")
        .exists()
    )


def calendar_management_action_visible(
    context: DataviewActionContext, *, original: Callable[[DataviewActionContext], bool]
) -> bool:
    """Keep management controls outside Inbox calendars while retaining their original permission gates."""
    return not back_to_inbox_visible(context) and original(context)


def calendar_event_dataview_actions() -> list[DataviewAction | DataviewHTMLAction]:
    """Add Inbox overlays and navigation to the ordinary CalendarEvent toolbar."""
    actions = [
        DataviewHTMLAction(
            id="add_calendars",
            template_name="models/calendar_event/align_calendars.html",
            should_render_func=calendar_overlay_visible,
        ),
    ]

    for default_action in get_default_dataview_actions():
        if default_action.id not in [
            "add",
        ]:
            default_action.should_render_func = partial(
                calendar_management_action_visible,
                original=default_action.should_render_func,
            )

        actions.append(default_action)

    actions.append(
        DataviewAction(
            id="back_to_inbox",
            label="Back to inbox",
            execution_func=back_to_inbox,
            method="GET",
            should_render_func=back_to_inbox_visible,
            icon="fa fa-inbox",
            target="#main-content",
        ),
    )
    return actions


class CalendarEvent(CalendarModel):
    """Store one meeting displayed in multiple Inbox calendars without copies."""

    bloomerp_config = BloomerpModelConfig(
        module=CommunicationModule,
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                CalendarDataView(
                    name="Calendar",
                    start_field="start",
                    end_field="end",
                    start_date_field="start_date",
                    end_date_field="end_date",
                    display_fields=["title"],
                    color_grouping_field="inboxes",
                )
            ],
            dataview_actions=calendar_event_dataview_actions(),
        ),
        object_actions=[
            ObjectAction(
                id="accept_invite",
                label="Accept invite",
                execution_func=lambda _,__:HttpResponse("Hey")
            )    
        ],
    )

    calendar_uid = models.CharField(
        max_length=255, default=new_calendar_uid, editable=False
    )
    sequence = models.PositiveIntegerField(default=0, editable=False)
    scheduling_dtstamp = models.DateTimeField(default=timezone.now, editable=False)
    cancelled = models.BooleanField(default=False, editable=False)
    source_calendar = models.TextField(blank=True, editable=False)
    invitation_sent_at = models.DateTimeField(null=True, blank=True, editable=False)

    inboxes = models.ManyToManyField(
        "bloomerp.Inbox",
        related_name="calendar_events",
        blank=True,
        verbose_name=_("Calendar inboxes"),
    )
    calendar_booking_submission = models.OneToOneField(
        "bloomerp.CalendarBookingSubmission",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="calendar_event",
        verbose_name=_("Booking submission"),
    )
    organizing_inbox = models.ForeignKey(
        "bloomerp.Inbox",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="organized_calendar_events",
        verbose_name=_("Organizing inbox"),
    )
    conference_session = models.OneToOneField(
        "bloomerp.ConferenceSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendar_event",
        editable=False,
        verbose_name=_("Conference session"),
    )
    organizer_email = models.EmailField(_("Organizer email"))
    title = models.CharField(_("Title"), max_length=255)
    content = models.TextField(_("Content"), blank=True)
    location = models.CharField(_("Location"), max_length=255, blank=True)
    start = models.DateTimeField(_("Start"), null=True, blank=True)
    end = models.DateTimeField(_("End"), null=True, blank=True)
    event_timezone = models.CharField(
        _("Event timezone"),
        max_length=255,
        null=True,
        blank=True,
        validators=[validate_calendar_timezone],
    )
    start_date = models.DateField(_("Start date"), null=True, blank=True)
    end_date = models.DateField(_("Exclusive end date"), null=True, blank=True)
    all_day = models.BooleanField(_("All day"), default=False)

    class Meta(CalendarModel.Meta):
        verbose_name = _("Calendar event")
        verbose_name_plural = _("Calendar events")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                models.F("calendar_uid"),
                models.functions.Lower("organizer_email"),
                name="calendar_uid_organizer_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        all_day=True,
                        start__isnull=True,
                        end__isnull=True,
                        event_timezone__isnull=True,
                        start_date__isnull=False,
                        end_date__isnull=False,
                        end_date__gt=models.F("start_date"),
                    )
                    | (
                        models.Q(
                            all_day=False,
                            start__isnull=False,
                            end__isnull=False,
                            event_timezone__isnull=False,
                            start_date__isnull=True,
                            end_date__isnull=True,
                            end__gt=models.F("start"),
                        )
                        & ~models.Q(event_timezone="")
                    )
                ),
                name="calendar_event_valid_time_range",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Keep sent identities stable and prevent local edits to imported meeting data."""
        previous = (
            type(self).objects.filter(pk=self.pk).first()
            if not self._state.adding
            else None
        )
        if previous is not None:
            if (previous.source_calendar or previous.invitation_sent_at) and (
                self.calendar_uid != previous.calendar_uid
                or self.organizer_email.lower() != previous.organizer_email.lower()
            ):
                raise ValidationError(
                    "A scheduled meeting's UID and organizer identity cannot be changed."
                )
            if (
                previous.source_calendar
                and previous.organizing_inbox_id is None
                and not getattr(self, "_applying_scheduling_message", False)
            ):
                fields = (
                    "title",
                    "content",
                    "location",
                    "start",
                    "end",
                    "start_date",
                    "end_date",
                    "all_day",
                    "event_timezone",
                    "organizing_inbox_id",
                    "sequence",
                    "scheduling_dtstamp",
                    "cancelled",
                    "source_calendar",
                )
                if any(
                    getattr(self, name) != getattr(previous, name) for name in fields
                ):
                    raise ValidationError(
                        "Imported meeting details must be updated by their external organizer."
                    )
        try:
            super().save(*args, **kwargs)
        finally:
            self._applying_scheduling_message = False

    def clean(self) -> None:
        """Reject naive timed instants before Django can assume a timezone."""
        super().clean()
        errors = {}
        for field in ("start", "end"):
            value = getattr(self, field)
            if isinstance(value, datetime) and timezone.is_naive(value):
                errors[field] = _("Use a timezone-aware instant.")
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        """Return the shared meeting's title independently of its placements."""
        return self.title

    def is_internal(self) -> bool:
        """Return whether every invited participant is linked to a Bloomerp user."""
        return not self.participants.filter(user__isnull=True).exists()

    def is_host(self, user: "AbstractBloomerpUser") -> bool:
        """Identify a locally hosted event's creator or organizing calendar owner."""
        return bool(self.organizing_inbox_id and (
            self.created_by_id == user.pk or self.organizing_inbox.user_id == user.pk
        ))

    def get_participant(self, user: "AbstractBloomerpUser") -> "CalendarEventParticipant | None":
        """Resolve a linked user or an invited external mailbox the caller can use."""
        if not user.is_authenticated:
            return None
        participants = self.participants.filter(invitation_cancelled=False)
        participant = participants.filter(user=user).first()
        if participant is not None or self.organizing_inbox_id:
            return participant
        from bloomerp.communication.utils.permissions import accessible_inboxes
        from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
        from bloomerp.services.email_composer_services import accessible_email_accounts

        folders = InboxFolder.objects.filter(
            inbox__in=self.inboxes.filter(pk__in=accessible_inboxes(user)), type="email"
        )
        for account in accessible_email_accounts(user).filter(status="active"):
            if folders.filter(related_object_id=str(account.pk)).exists():
                participant = participants.filter(email__iexact=account.email_address).first()
                if participant is not None:
                    return participant
        return None

    def get_absolute_url(self) -> str:
        """
        Returns the absolute URL of the model instance.
        """
        return reverse("calendar_events_detail_update", kwargs={'pk': self.pk})
