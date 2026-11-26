"""Visitor booking details retained independently of the resulting shared event."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse
from django.template.defaultfilters import urlize
from django.utils import formats, timezone
from django.utils.html import format_html, format_html_join, linebreaks, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_noop
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.definition import (
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    get_default_object_actions,
)
from bloomerp.permissions.definition import BloomerpPermission, PermissionMatch
from bloomerp.utils.requests import render_message
from bloomerp.utils.rich_text import format_content, sanitize_html
from bloomerp.widgets.booking_location_widget import CREATE_BOOKING_CONFERENCE

from .base import CalendarModel

if TYPE_CHECKING:
    from bloomerp.models.communication.email_account import EmailAccount
    from bloomerp.models.users.user import AbstractBloomerpUser

    from .booking_link import BookingLink
    from .calendar_event import CalendarEvent


logger = logging.getLogger(__name__)


def scope_booking_link_submissions(
    _request: HttpRequest, queryset: models.QuerySet, args: dict[str, str],
) -> models.QuerySet:
    """Intersect the viewer's submissions with the link in the signed dataview."""
    if "booking_link" in args:
        return queryset.filter(booking_link_id=args["booking_link"])
    return queryset


def can_show_booking_approval(context: ObjectActionContext) -> bool:
    """Offer approval to authorized organizers reviewing a pending submission."""
    submission = cast(BookingLinkSubmission, context.object)
    return bool(
        submission.requested_start
        and submission.requested_end
        and submission.may_approve(context.request.user)
        and not hasattr(submission, "calendar_event")
    )


def approve_booking_action(context: ObjectActionContext) -> HttpResponse | None:
    """Confirm the request using the instance origin for generated join URLs."""
    submission = cast(BookingLinkSubmission, context.object)
    try:
        submission.approve(
            context.request.user,
            meeting_base_url=context.request.build_absolute_uri("/"),
        )
    except ValidationError as error:
        return render_message(context.request, " ".join(error.messages), "error")
    return None


def booking_submission_actions(model: type[models.Model]) -> list[ObjectActionDefinition]:
    """Add the POST approval action to the standard submission actions."""
    return [
        ObjectAction(
            id="approve_booking",
            label=gettext_noop("Approve booking"),
            icon="fa-solid fa-check",
            method="POST",
            execution_func=approve_booking_action,
            should_render_func=can_show_booking_approval,
            refresh_on_success="item",
            success_message=gettext_noop("Booking approved."),
        ),
        *get_default_object_actions(model),
    ]


class BookingLinkSubmission(CalendarModel):
    """Record visitor details and retain proposed times for manual approval."""

    bloomerp_config = BloomerpModelConfig(
        module="communication",
        object_actions=booking_submission_actions,
        model_view_settings=ModelViewSettings(
            embedded_queryset_scope=scope_booking_link_submissions,
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("Booking link submissions"),
                    display_fields=["name", "email", "booking_link", "submitted_at"],
                    sort_field="submitted_at",
                    sort_direction="desc",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Visitor"),
                            items=[LayoutItem(id="name"), LayoutItem(id="email")],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Booking"),
                            items=[
                                LayoutItem(id="booking_link"),
                                LayoutItem(id="submitted_at"),
                                LayoutItem(id="requested_start"),
                                LayoutItem(id="requested_end"),
                            ],
                        ),
                    ]
                )
            ]
        ),
    )

    booking_link = models.ForeignKey(
        "bloomerp.BookingLink",
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name=_("Booking link"),
    )
    name = models.CharField(_("Name"), max_length=255)
    email = models.EmailField(_("Email"))
    submitted_at = models.DateTimeField(_("Submitted at"), default=timezone.now)
    requested_start = models.DateTimeField(_("Requested start"), null=True, blank=True)
    requested_end = models.DateTimeField(_("Requested end"), null=True, blank=True)

    class Meta(CalendarModel.Meta):
        db_table = "bloomerp_calendarbookingsubmission"
        verbose_name = _("Booking link submission")
        verbose_name_plural = _("Booking link submissions")

    def __str__(self) -> str:
        """Identify a submission by its visitor and email address."""
        return f"{self.name} <{self.email}>"

    def may_approve(self, user: "AbstractBloomerpUser") -> bool:
        """Require submission write access and authority over its organizing inbox."""
        from bloomerp.permissions.manager import UserPolicyManager

        return bool(
            user.is_authenticated
            and (
                user.is_superuser
                or self.booking_link.organizing_inbox.effective_preference.user_id == user.pk
            )
            and UserPolicyManager(user).has_access_to_object(
                self, [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
                match=PermissionMatch.ALL,
            )
        )

    @transaction.atomic
    def approve(self, user: "AbstractBloomerpUser", *, meeting_base_url: str) -> "CalendarEvent":
        """Confirm a still-available manual request once under scheduling locks."""
        link, inbox_ids = self.booking_link.lock_scheduling_scope()
        submission = type(self).objects.select_for_update().filter(
            pk=self.pk, booking_link=link,
        ).first()
        if submission is None or not submission.may_approve(user):
            raise PermissionDenied
        event = getattr(submission, "calendar_event", None)
        if event is not None:
            return event
        start, end = submission.requested_start, submission.requested_end
        if start is None or end is None:
            raise ValidationError(_("This booking has no requested time."))
        link.require_available_slot(start, end, inbox_ids)
        return submission.create_confirmed_event(
            link=link, start=start, end=end, inbox_ids=inbox_ids,
            meeting_base_url=meeting_base_url,
        )

    def create_confirmed_event(
        self, *, link: "BookingLink", start: datetime, end: datetime,
        inbox_ids: set[int], meeting_base_url: str,
    ) -> "CalendarEvent":
        """Create the calendar event and its resolved location within the booking transaction."""
        from .calendar_event import CalendarEvent
        from .calendar_event_participant import CalendarEventParticipant

        organizer_inbox = link.organizing_inbox.effective_preference
        organizer = organizer_inbox.user
        account_id, message = link.email_account_id, link.email_message
        sender = self.confirmation_email_account(organizer, account_id) if account_id and message else None
        create_meeting = link.location == CREATE_BOOKING_CONFERENCE
        event = CalendarEvent.objects.create(
            title=link.title,
            content=link.description,
            location="" if create_meeting else link.location,
            start=start,
            end=end,
            event_timezone=link.timezone,
            organizing_inbox=organizer_inbox,
            organizer_email=sender.email_address if sender else (
                organizer.email or f"user-{organizer.pk}@calendar.invalid"
            ),
            calendar_booking_submission=self,
        )
        event.inboxes.set(inbox_ids)
        event.participants.create(
            display_name=self.name,
            email=self.email,
            response_status=CalendarEventParticipant.ResponseStatus.ACCEPTED,
            responded_at=self.submitted_at,
        )
        if create_meeting:
            try:
                event.location = event.reserve_conference(organizer, (), meeting_base_url)
            except ImproperlyConfigured as error:
                raise ValidationError(
                    _("Conferencing is unavailable for this instance.")
                ) from error
            event.save(update_fields=["location"])
        if sender is not None and message:
            account_id = sender.pk

            def send_after_commit() -> None:
                """Send the invitation only after the event and its location are saved."""
                self.send_confirmation_email(event, account_id, message)

            transaction.on_commit(send_after_commit, robust=True)
        return event

    @staticmethod
    def confirmation_email_account(
        organizer: "AbstractBloomerpUser", account_id: UUID,
    ) -> "EmailAccount | None":
        """Resolve an active confirmation sender the organizing inbox owner can use."""
        from bloomerp.models.communication.email_account import EmailAccount
        from bloomerp.services.email_composer_services import accessible_email_accounts

        if not organizer.is_active:
            return None
        return accessible_email_accounts(organizer).filter(
            pk=account_id, status=EmailAccount.Status.ACTIVE,
        ).first()

    def send_confirmation_email(self, event: "CalendarEvent", account_id: UUID, message: str) -> None:
        """Send the booking message and the event's initial iCalendar request together."""
        from bloomerp.communication.builtins.emails.actions import (
            _resolve_email_adapter_for_account,
        )
        from bloomerp.communication.builtins.emails.base_adapter import (
            EmailAttachment,
            EmailSendUnconfirmed,
        )
        from bloomerp.communication.builtins.emails.sending import store_outbound_email
        from bloomerp.communication.calendar.ical import build_scheduling_calendar
        from bloomerp.communication.calendar.outgoing import calendar_send_key

        account = self.confirmation_email_account(event.organizing_inbox.user, account_id)
        if account is None or account.email_address.lower() != event.organizer_email.lower():
            logger.warning("No authorized booking confirmation sender for submission %s", self.pk)
            return
        if event.start is None or event.end is None or not event.event_timezone:
            raise ValueError("A booking confirmation requires a timed event and timezone.")

        zone = ZoneInfo(event.event_timezone)
        start, end = timezone.localtime(event.start, zone), timezone.localtime(event.end, zone)
        dates = formats.date_format(start, "DATE_FORMAT")
        if start.date() != end.date():
            dates = f'{dates} – {formats.date_format(end, "DATE_FORMAT")}'
        times = f'{formats.time_format(start, "TIME_FORMAT")} – {formats.time_format(end, "TIME_FORMAT")}'
        details = [
            (gettext("Date"), dates),
            (gettext("Time"), times),
            (gettext("Timezone"), event.event_timezone),
        ]
        if event.location:
            details.append((gettext("Location"), event.location))

        subject = gettext("Booking confirmed: %(title)s") % {"title": " ".join(event.title.split())}
        message_html = sanitize_html(message)
        if strip_tags(message_html) == message_html:
            message_html = linebreaks(message_html)
        message_text = format_content(message, "plain")
        body_text = "\n".join([message_text, "", *(f"{label}: {value}" for label, value in details)])
        body_html = format_html(
            "{}<dl>{}</dl>",
            mark_safe(message_html),
            format_html_join("", "<dt>{}</dt><dd>{}</dd>", (
                (label, urlize(value)) for label, value in details
            )),
        )
        attendee = event.participants.get(email__iexact=self.email)
        stamp = event.scheduling_dtstamp.replace(microsecond=0)
        method = "REQUEST"
        payload = build_scheduling_calendar(event, method, [attendee], stamp=stamp)
        recipients = [attendee.email]
        adapter = _resolve_email_adapter_for_account(account)
        try:
            pending = False
            try:
                result = adapter.send_email(
                    to=recipients, subject=subject, body_text=body_text, body_html=body_html,
                    attachments=[
                        EmailAttachment(
                            filename="invite.ics", content=payload,
                            content_type="text/calendar", calendar_method=method,
                        )
                    ],
                )
            except EmailSendUnconfirmed as error:
                result, pending = error.result, True
                logger.warning("Unconfirmed booking email for submission %s", self.pk)
            if not pending:
                event.invitation_sent_at = stamp
                event.save(update_fields=["invitation_sent_at"])
            items = store_outbound_email(
                account=account, result=result, body_html=body_html,
                form_data={"to": recipients, "subject": subject, "body": body_text},
                pending=pending,
            )
            send_key = calendar_send_key(account, event, method, payload, recipients)
            for item in items:
                item.raw_meta_data.update(calendar_event_id=str(event.pk), calendar_send_key=send_key)
                item.save(update_fields=["raw_meta_data"])
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
