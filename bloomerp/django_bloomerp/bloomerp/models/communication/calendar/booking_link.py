"""Reusable public booking configuration, separate from visitor submissions."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, cast
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import connection, models, transaction
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from pydantic import ValidationError as ScheduleValidationError

from bloomerp.communication.calendar.booking_availability import BookingLinkAvailability
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.field_types.registry import FieldContext
from bloomerp.field_types.utils.form_field_factories import form
from bloomerp.field_types.utils.widget_factories import widget
from bloomerp.form_fields.booking_availability_field import BookingAvailabilityField
from bloomerp.form_fields.booking_email_account_field import BookingEmailAccountField
from bloomerp.form_fields.booking_location_field import BookingLocationField
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    FieldSettings,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    get_default_object_actions,
)
from bloomerp.widgets.booking_availability_widget import BookingAvailabilityWidget
from bloomerp.widgets.booking_email_account_widget import BookingEmailAccountWidget
from bloomerp.widgets.booking_location_widget import BookingLocationWidget

from .base import CalendarModel
from .validators import validate_calendar_timezone

if TYPE_CHECKING:
    from .booking_link_submission import BookingLinkSubmission

COPY_BOOKING_LINK_ACTION = "share_booking_link"


def booking_link_settings_rows() -> list[LayoutRow]:
    """Define the booking fields that the organizing inbox owner can manage."""
    return [
        LayoutRow(
            columns=2,
            title=gettext_noop("Booking"),
            items=[
                LayoutItem(id="title"),
                LayoutItem(id="active"),
                LayoutItem(id="auto_approve"),
                LayoutItem(id="location", colspan=2),
                LayoutItem(id="description", colspan=2),
            ],
        ),
        LayoutRow(
            columns=2,
            title=gettext_noop("Availability"),
            items=[
                LayoutItem(id="meeting_duration_minutes"),
                LayoutItem(id="timezone"),
                LayoutItem(id="availability_hours", colspan=2),
            ],
        ),
        LayoutRow(
            columns=1,
            title=gettext_noop("Email"),
            items=[LayoutItem(id="email_account"), LayoutItem(id="email_message")],
        ),
    ]


def availability_timezone_widget(context: FieldContext) -> forms.Select:
    """Offer the Calendar Event timezone choices in booking forms."""
    from bloomerp.forms.communication.calendar_event import calendar_timezone_choices

    return forms.Select(
        attrs=context.attrs,
        choices=[
            ("", _("Choose a timezone")),
            *calendar_timezone_choices(timezone.now()),
        ],
    )


def booking_email_account_widget(context: FieldContext) -> forms.Select:
    """Render the scoped sender choices when the framework builds the layout widget."""
    from bloomerp.models.communication.email_account import EmailAccount

    field = BookingEmailAccountField(
        queryset=EmailAccount.objects.all(),
        required=False,
        widget=BookingEmailAccountWidget(attrs=context.attrs),
    )
    return field.widget


def scope_embedded_booking_links(
    request: HttpRequest,
    queryset: models.QuerySet,
    args: dict[str, str],
) -> models.QuerySet:
    """Keep links that match the selected inbox through an association the viewer may read."""
    from bloomerp.communication.calendar.access import resolve_calendar_inbox
    from bloomerp.models.application_field import ApplicationField
    from bloomerp.permissions.manager import (
        UserPolicyManager,
        field_access_annotation_name,
    )

    if "booking_inbox" not in args:
        return queryset
    inbox = resolve_calendar_inbox(request.user, int(args["booking_inbox"]))
    fields = list(
        ApplicationField.get_for_model(BookingLink).filter(
            field__in=("organizing_inbox", "target_inboxes"),
        )
    )
    scope = models.Q(pk__in=[])
    for field in fields:
        scope |= models.Q(
            **{field.field: inbox.pk, field_access_annotation_name(field): True}
        )
    return (
        UserPolicyManager(request.user)
        .annotate_field_permissions(
            queryset,
            fields,
            "view",
        )
        .filter(scope)
        .distinct()
    )


def booking_link_object_actions(
    model: type[models.Model],
) -> list[ObjectActionDefinition]:
    """Add the standard copy button to each eligible booking record."""
    return [
        *get_default_object_actions(model),
        ObjectAction(
            id=COPY_BOOKING_LINK_ACTION,
            label=gettext_noop("Copy booking link"),
            icon="fa-solid fa-link",
            should_render_func=can_copy_booking_link,
            button_attrs=booking_link_copy_button_attrs,
        ),
    ]


def can_copy_booking_link(context: ObjectActionContext) -> bool:
    """Offer the button for active records whose status the viewer may read."""
    from bloomerp.permissions.manager import UserPolicyManager

    link = cast(BookingLink, context.object)
    return (
        link.active
        and UserPolicyManager(context.request.user)
        .get_accessible_fields_for_object(link, "view")
        .filter(field="active")
        .exists()
    )


def booking_link_copy_button_attrs(context: ObjectActionContext) -> dict[str, str]:
    """Expose the authorized booking URL to the existing clipboard helper."""
    link = cast(BookingLink, context.object)
    return {
        "x-data": "",
        "data-booking-url": context.request.build_absolute_uri(link.get_public_url()),
        "@click": "copyToClipboard($el.dataset.bookingUrl)",
    }


class BookingLink(CalendarModel):
    """Configure a booking offering without inferring attendees from inboxes."""

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        object_actions=booking_link_object_actions,
        field_settings=[
            FieldSettings(
                field="timezone", widget_factory=availability_timezone_widget
            ),
            FieldSettings(
                field="availability_hours",
                form_factory=form(BookingAvailabilityField),
                widget_factory=widget(BookingAvailabilityWidget),
            ),
            FieldSettings(
                field="location",
                form_factory=form(BookingLocationField),
                widget_factory=widget(BookingLocationWidget),
            ),
            FieldSettings(
                field="email_account",
                form_factory=form(BookingEmailAccountField),
                widget_factory=booking_email_account_widget,
            ),
            FieldSettings(
                field="email_message",
                widget_factory=widget(forms.Textarea, attrs={"rows": 4}),
            ),
        ],
        model_view_settings=ModelViewSettings(
            embedded_queryset_scope=scope_embedded_booking_links,
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Booking links"),
                    display_fields=[
                        "title",
                        "organizing_inbox",
                        "meeting_duration_minutes",
                        "timezone",
                        "active",
                    ],
                    sort_field="title",
                )
            ],
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        *booking_link_settings_rows(),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Inboxes"),
                            items=[
                                LayoutItem(id="organizing_inbox"),
                                LayoutItem(id="target_inboxes"),
                            ],
                        ),
                    ]
                )
            ]
        ),
    )

    organizing_inbox = models.ForeignKey(
        "bloomerp.Inbox",
        on_delete=models.PROTECT,
        related_name="organized_calendar_bookings",
        verbose_name=_("Organizing inbox"),
    )
    target_inboxes = models.ManyToManyField(
        "bloomerp.Inbox",
        related_name="calendar_bookings",
        blank=True,
        verbose_name=_("Destination inboxes"),
    )
    title = models.CharField(_("Title"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    location = models.CharField(_("Location"), max_length=255, blank=True)
    meeting_duration_minutes = models.PositiveIntegerField(
        _("Meeting duration in minutes"),
        validators=[MinValueValidator(1)],
    )
    availability_hours = models.JSONField(
        _("Availability hours"), default=dict, blank=True
    )
    timezone = models.CharField(
        _("Availability timezone"),
        max_length=255,
        default=timezone.get_default_timezone_name,
        validators=[validate_calendar_timezone],
    )
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    active = models.BooleanField(_("Active"), default=False)
    auto_approve = models.BooleanField(_("Auto approve"), default=True)
    email_account = models.ForeignKey(
        "bloomerp.EmailAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_links",
        verbose_name=_("Email account"),
    )
    email_message = models.TextField(
        _("Email message"),
        null=True,
        blank=True,
        help_text=_("Required when an email account is selected."),
    )

    class Meta(CalendarModel.Meta):
        db_table = "bloomerp_calendarbooking"
        verbose_name = _("Booking link")
        verbose_name_plural = _("Booking links")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(meeting_duration_minutes__gt=0),
                name="calendar_booking_positive_duration",
            ),
            models.CheckConstraint(
                condition=models.Q(email_account__isnull=True)
                | (models.Q(email_message__isnull=False) & ~models.Q(email_message="")),
                name="booking_link_email_message_required",
                violation_error_message=_(
                    "Enter an email message when an email account is selected."
                ),
                violation_error_code="email_message_required",
            ),
        ]

    def __str__(self) -> str:
        """Return the offering's title independently of its destination inboxes."""
        return self.title

    def clean(self) -> None:
        """Normalize empty messages and require sender access to change delivery settings."""
        from bloomerp.middleware import current_request
        from bloomerp.services.email_composer_services import accessible_email_accounts

        super().clean()
        if not (self.email_message or "").strip():
            self.email_message = None
        request = current_request()
        user = getattr(request, "user", None)
        if self.email_account_id is None or user is None or not user.is_authenticated:
            return
        previous = None
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values_list(
                "email_account_id", "email_message", "organizing_inbox_id",
            ).first()
        settings = (self.email_account_id, self.email_message, self.organizing_inbox_id)
        if previous != settings and not (
            accessible_email_accounts(user).filter(pk=self.email_account_id).exists()
        ):
            raise PermissionDenied(_("You cannot use the selected email account."))

    def get_availability(self) -> BookingLinkAvailability:
        """Read the typed schedule, treating unusable legacy hours as closed."""
        try:
            return BookingLinkAvailability.model_validate(self.availability_hours)
        except ScheduleValidationError:
            return BookingLinkAvailability()

    def get_public_url(self) -> str:
        """Return the UUID-based detail URL that visitors can use to book."""
        return reverse(
            "booking_links_detail_booking_link_submission",
            kwargs={"pk": self.pk},
        )

    def booking_inbox_ids(self) -> set[int]:
        """Resolve the organizer and destinations to their effective calendars."""
        return {
            self.organizing_inbox.effective_preference.pk,
            *(inbox.effective_preference.pk for inbox in self.target_inboxes.all()),
        }

    def available_slots(
        self,
        first_day: date,
        last_day: date,
        *,
        inbox_ids: set[int] | None = None,
        duration: timedelta | None = None,
    ) -> dict[date, list[datetime]]:
        """Return future, conflict-free slot starts grouped by local booking date."""
        from .calendar_event import CalendarEvent

        schedule = self.get_availability()
        zone = ZoneInfo(self.timezone)
        now = timezone.now()
        if duration is None:
            duration = timedelta(minutes=self.meeting_duration_minutes)
        if duration <= timedelta(0):
            return {}
        first_day = max(first_day, now.astimezone(zone).date())
        candidates: dict[date, list[datetime]] = {}
        for ordinal in range(first_day.toordinal(), last_day.toordinal() + 1):
            day = date.fromordinal(ordinal)
            starts: set[datetime] = set()
            for hours in schedule.hours_on(day):
                window_start = datetime.combine(day, hours.start)
                wall_end = datetime.combine(day, hours.end)
                wall_start = window_start
                while duration <= wall_end - wall_start:
                    for fold in (0, 1):
                        start = wall_start.replace(tzinfo=zone, fold=fold).astimezone(
                            UTC
                        )
                        last_instant = start + duration - timedelta(microseconds=1)
                        last_wall = last_instant.astimezone(zone).replace(tzinfo=None)
                        if (
                            start > now
                            and start.astimezone(zone).replace(tzinfo=None)
                            == wall_start
                            and window_start <= last_wall < wall_end
                        ):
                            starts.add(start)
                    wall_start += duration
            if starts:
                candidates[day] = sorted(starts)
        if not candidates:
            return {}

        if inbox_ids is None:
            inbox_ids = self.booking_inbox_ids()
        events = (
            CalendarEvent.objects.filter(cancelled=False)
            .filter(
                models.Q(inboxes__in=inbox_ids)
                | models.Q(organizing_inbox_id__in=inbox_ids)
            )
            .filter(
                models.Q(
                    start__lt=max(starts[-1] for starts in candidates.values())
                    + duration,
                    end__gt=min(starts[0] for starts in candidates.values()),
                )
                | models.Q(start_date__lte=last_day, end_date__gt=first_day)
            )
            .values_list("start", "end", "start_date", "end_date")
            .distinct()
        )
        timed_busy = []
        all_day_busy = []
        for start, end, start_date, end_date in events:
            if start_date is not None:
                all_day_busy.append((start_date, end_date))
            else:
                timed_busy.append((start, end))
        return {
            day: free
            for day, starts in candidates.items()
            if not any(begin <= day < end for begin, end in all_day_busy)
            if (
                free := [
                    start
                    for start in starts
                    if not any(
                        begin < start + duration and start < end
                        for begin, end in timed_busy
                    )
                ]
            )
        }

    def lock_scheduling_scope(self, *, active_only: bool = False) -> tuple["BookingLink", set[int]]:
        """Lock the link and its effective calendars inside the caller's transaction."""
        from bloomerp.models.communication.inbox.inbox import Inbox

        links = BookingLink.objects.filter(pk=self.pk)
        if active_only:
            links = links.filter(active=True)
        if connection.vendor == "sqlite":
            # Acquire SQLite's write lock before reading the calendar in this transaction.
            links.update(active=models.F("active"))
        link = links.select_for_update().get()
        inbox_ids = link.booking_inbox_ids()
        # Different links may reserve the same calendar. Acquire shared locks in order.
        list(Inbox.objects.select_for_update().filter(pk__in=inbox_ids).order_by("pk"))
        return link, inbox_ids

    def require_available_slot(
        self, start: datetime, end: datetime, inbox_ids: set[int]
    ) -> None:
        """Reject an interval that can no longer be scheduled on the locked calendars."""
        day = start.astimezone(ZoneInfo(self.timezone)).date()
        if end <= start or start not in self.available_slots(
            day, day, inbox_ids=inbox_ids, duration=end - start
        ).get(day, ()):
            raise ValidationError(
                _("This time is no longer available. Choose another time.")
            )

    @transaction.atomic
    def submit_slot(
        self, *, start: datetime, name: str, email: str, meeting_base_url: str
    ) -> "tuple[BookingLinkSubmission | None, bool]":
        """Record the request and confirm it immediately if configured to do so."""
        link, inbox_ids = self.lock_scheduling_scope(active_only=True)
        end = start + timedelta(minutes=link.meeting_duration_minutes)
        link.require_available_slot(start, end, inbox_ids)
        if not link.auto_approve:
            if link.submissions.filter(
                email__iexact=email, requested_start=start, calendar_event__isnull=True
            ).exists():
                return None, False
            pending = link.submissions.create(
                name=name, email=email, requested_start=start, requested_end=end
            )
            return pending, False

        submission = link.submissions.create(name=name, email=email)
        submission.create_confirmed_event(
            link=link, start=start, end=end, inbox_ids=inbox_ids,
            meeting_base_url=meeting_base_url,
        )
        return submission, True
