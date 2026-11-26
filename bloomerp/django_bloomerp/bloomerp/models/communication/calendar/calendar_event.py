"""Shared meetings with independent calendar placement and organizer identity."""

from collections.abc import Callable, Iterable
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlencode, urljoin

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, gettext_noop
from django.utils.translation import gettext_lazy as _
from django_htmx.http import HttpResponseLocation

from bloomerp.dataviews.calendar.config import CalendarDataView
from bloomerp.filters.definition import FilterCondition
from bloomerp.models.actions.dataview.builtins import get_default_dataview_actions
from bloomerp.models.actions.dataview.call_dataview import (
    call_dataview_action,
)
from bloomerp.models.actions.object.builtins import get_default_object_actions
from bloomerp.models.actions.permissions import can_add_model
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DataviewAction,
    DataviewActionContext,
    DataviewActionDefinition,
    DataviewHTMLAction,
    DetailTab,
    DetailTabsConfiguration,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectActionContext,
    ObjectModalAction,
)
from bloomerp.modules.communication import CommunicationModule
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleContent,
)
from bloomerp.tokens import (
    DataviewToken,
    DetailViewToken,
    RequestToken,
)

from .base import CalendarModel
from .booking_link import (
    COPY_BOOKING_LINK_ACTION,
    BookingLink,
    booking_link_settings_rows,
)
from .booking_link_submission import BookingLinkSubmission
from .validators import new_calendar_uid, validate_calendar_timezone

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox import Inbox
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


def calendar_booking_inbox(context: DataviewActionContext) -> "Inbox | None":
    """Resolve the current inbox independently from the visible calendar overlays."""
    from bloomerp.communication.calendar.access import resolve_calendar_inbox

    if not context.request.user.is_authenticated:
        return None
    try:
        inbox_id = int(context.request.GET.get("_arg_calendar_inbox", ""))
        return resolve_calendar_inbox(context.request.user, inbox_id)
    except (Http404, ValueError):
        return None


def calendar_booking_create_visible(context: DataviewActionContext) -> bool:
    """Offer booking creation to the inbox owner and viewers with ordinary add access."""
    inbox = calendar_booking_inbox(context)
    return inbox is not None and (
        inbox.user_id == context.request.user.pk or can_add_model(context.request, BookingLink)
    )


def calendar_booking_owner_conditions(
    inbox: "Inbox", user: "AbstractBloomerpUser"
) -> list[FilterCondition]:
    """Restrict a booking grant to one organizing inbox and its current owner."""
    return [
        FilterCondition(
            field_path="organizing_inbox", lookup_id="equals", value=str(inbox.pk)
        ),
        FilterCondition(
            field_path="organizing_inbox__user", lookup_id="equals", value=str(user.pk)
        ),
    ]


def calendar_booking_links_visible(context: DataviewActionContext) -> bool:
    """Offer the management drawer when this inbox's bookings can be read or created."""
    from bloomerp.permissions.manager import UserPolicyManager

    inbox = calendar_booking_inbox(context)
    return inbox is not None and (
        inbox.user_id == context.request.user.pk
        or can_add_model(context.request, BookingLink)
        or UserPolicyManager(context.request.user).has_global_permission(BookingLink, "view")
    )


def calendar_booking_links_token(context: DataviewActionContext) -> RequestToken | None:
    """Configure booking management for the current inbox and viewer."""
    from bloomerp.permissions.manager import UserPolicyManager

    inbox = calendar_booking_inbox(context)
    if inbox is None:
        return None
    user = context.request.user
    layout = next(
        view for view in BookingLink.bloomerp_config.model_view_settings.default_dataviews
        if view.is_default
    )
    layout = layout.model_copy(update={
        "view_mode": "drawer",
        "component_args": {**layout.component_args, "booking_inbox": str(inbox.pk)},
    })
    can_create = calendar_booking_create_visible(context)
    view = BloomerpPermission.VIEW
    can_view_model = UserPolicyManager(user).has_global_permission(BookingLink, view)
    rows = booking_link_settings_rows()
    detail_layout = FieldLayout(rows=rows)
    create_rows = list(rows)
    if can_add_model(context.request, BookingLink):
        create_rows.append(LayoutRow(columns=2, title=gettext_noop("Inboxes"), items=[
            LayoutItem(id="organizing_inbox"), LayoutItem(id="target_inboxes"),
        ]))
    content_type = ContentType.objects.get_for_model(BookingLink)
    create_url = reverse("components_create_object", kwargs={"content_type_id": content_type.pk})
    create_url = f"{create_url}?{urlencode({'organizing_inbox': str(inbox.pk)})}"
    if can_view_model:
        detail_settings = BookingLink.bloomerp_config.detail_view_settings
        detail_layout = detail_settings.get_default_layout() or detail_layout
    permission_rule = None
    if inbox.user_id == user.pk:
        view_and_change = [view, BloomerpPermission.CHANGE]
        add = BloomerpPermission.ADD
        permission_rule = AccessRule(
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=[*view_and_change, add],
                    conditions=calendar_booking_owner_conditions(inbox, user),
                )
            ],
            field_permissions={
                "organizing_inbox": [view, add],
                "submissions": [view],
                **{str(item.id): [*view_and_change, add] for row in rows for item in row.items},
            },
        )
    elif not can_view_model:
        # A shared-inbox viewer with add-only access can open the drawer to create links.
        permission_rule = AccessRule(
            row_permissions=[RowPolicyRuleContent(connector="OR", permissions=[view])]
        )
    policies = {BookingLink: permission_rule} if permission_rule is not None else {}
    if inbox.user_id == user.pk:
        policies[BookingLinkSubmission] = AccessRule(
            row_permissions=[RowPolicyRuleContent(
                permissions=[view],
                conditions=[
                    FilterCondition(
                        field_path=f"booking_link__{condition.field_path}",
                        lookup_id=condition.lookup_id,
                        value=condition.value,
                    )
                    for condition in calendar_booking_owner_conditions(inbox, user)
                ],
            )],
            field_permissions={
                name: [view] for name in (
                    "name", "email", "booking_link", "submitted_at", "requested_start", "requested_end",
                )
            },
        )
    submission_layout = next(
        view for view in BookingLinkSubmission.bloomerp_config.model_view_settings.default_dataviews
        if view.is_default
    )
    booking_dataview = DataviewToken(
        dataview=layout,
        object_actions=[COPY_BOOKING_LINK_ACTION],
        dataview_actions=["add"] if can_create else [],
        create_url=create_url if can_create else None,
        hide_filters=True,
    )
    booking_detail_view = DetailViewToken(
        field_layout=detail_layout,
        tab_configuration=DetailTabsConfiguration(
            tabs=[
                DetailTab(name=gettext("Details"), url_name="booking_links_detail_overview"),
                DetailTab(
                    name=gettext("Submissions"),
                    url_name="booking_links_detail_submissions_relationship",
                ),
            ],
        ),
        object_actions=None if can_view_model else [COPY_BOOKING_LINK_ACTION],
    )
    return RequestToken(
        policies=policies,
        dataviews={
            BookingLink: booking_dataview,
            BookingLinkSubmission: DataviewToken(dataview=submission_layout),
        },
        detail_views={BookingLink: booking_detail_view},
        create_views={BookingLink: DetailViewToken(field_layout=FieldLayout(rows=create_rows))} if can_create else {},
    )


def calendar_event_dataview_actions(model: type[models.Model]) -> list[DataviewActionDefinition]:
    """Add Inbox overlays, bookings, and navigation to the CalendarEvent toolbar."""
    actions: list[DataviewActionDefinition] = [
        DataviewHTMLAction(
            id="add_calendars",
            template_name="models/calendar_event/align_calendars.html",
            should_render_func=calendar_overlay_visible,
        ),
        call_dataview_action(
            id="bookings",
            model=BookingLink,
            label=gettext_noop("Booking links"),
            icon="fa-regular fa-calendar-check",
            target="drawer",
            request_token=calendar_booking_links_token,
            should_render_func=calendar_booking_links_visible,
            size="4xl",
            body_class="p-4",
        ),
    ]

    for default_action in get_default_dataview_actions(model):
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
            execution_func=lambda context: HttpResponseLocation(reverse("inbox"), target="#main-content"),
            method="GET",
            should_render_func=back_to_inbox_visible,
            icon="fa fa-inbox",
            button_attrs={"hx-target": "#main-content"},
        ),
    )
    return actions


def calendar_invitation_reply_url(context: ObjectActionContext) -> str:
    """Resolve the dedicated attendance modal without using the event editor."""
    return reverse("components_calendar_reply", kwargs={"event_id": context.object.pk})


def calendar_invitation_reply_visible(context: ObjectActionContext) -> bool:
    """Offer replies only to an active invitation's non-host participant identity."""
    event = context.object
    user = context.request.user
    return bool(
        isinstance(event, CalendarEvent)
        and not event.cancelled
        and event.get_participant(user) is not None
        and not event.is_host(user)
    )


class CalendarEvent(CalendarModel):
    """Store one meeting displayed in multiple Inbox calendars without copies."""

    bloomerp_config = BloomerpModelConfig(
        module=CommunicationModule,
        detail_view_settings=DetailViewSettings(
            tab_configurations=[
                DetailTabsConfiguration(
                    tabs=[
                        DetailTab(name="Update", url_name="calendar_events_detail_update"),
                        DetailTab(name="Delete", url_name="calendar_events_detail_delete"),
                    ],
                ),
            ],
        ),
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
            dataview_actions=calendar_event_dataview_actions,
        ),
        object_actions=lambda model: [
            *get_default_object_actions(model),
            ObjectModalAction(
                id="reply_invitation",
                label="Reply to invitation",
                endpoint=calendar_invitation_reply_url,
                should_render_func=calendar_invitation_reply_visible,
                title="Reply to invitation",
            ),
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
        "bloomerp.BookingLinkSubmission",
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

    @transaction.atomic
    def reserve_conference(
        self,
        host: "AbstractBloomerpUser",
        attendees: Iterable["AbstractBloomerpUser"],
        base_url: str,
    ) -> str:
        """Reserve a pending conference for this saved event and return its join URL."""
        from bloomerp.communication.builtins.conferencing.configuration import (
            get_conferencing_settings,
        )
        from bloomerp.models.communication.conferencing import (
            ConferenceParticipant,
            ConferenceRoom,
            ConferenceSession,
        )

        get_conferencing_settings()
        room = ConferenceRoom.objects.create(title=self.title, created_by=host)
        session = ConferenceSession.objects.create(
            room=room, initial_media_mode="video", created_by=host
        )
        users = {person.pk: person for person in [host, *attendees]}
        for person in users.values():
            ConferenceParticipant.objects.create(
                session=session,
                user=person,
                display_name_snapshot=str(person),
                role="host" if person.pk == host.pk else "participant",
                created_by=host,
                invited_at=timezone.now(),
            )
        self.conference_session = session
        self.save(update_fields=["conference_session"])
        return urljoin(
            base_url,
            reverse("conference_sessions_meeting", kwargs={"token": session.share_token}),
        )

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
        if participant is not None or self.is_host(user):
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
