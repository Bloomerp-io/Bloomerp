"""Permission-checked scheduling actions using existing inbox email identities."""

from datetime import timedelta
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from bloomerp.communication.builtins.emails.actions import (
    _resolve_email_adapter_for_account,
)
from bloomerp.communication.builtins.emails.base_adapter import EmailAttachment
from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarEventParticipant,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.email_composer_services import accessible_email_accounts

from .ical import build_scheduling_calendar

EVENT_PAYLOAD_FIELDS = [
    "title",
    "content",
    "location",
    "start",
    "end",
    "event_timezone",
    "start_date",
    "end_date",
    "all_day",
    "cancelled",
    "organizer_email",
    "calendar_uid",
    "sequence",
    "scheduling_dtstamp",
]


def require_event_access(
    user: AbstractBloomerpUser,
    event: CalendarEvent,
    *,
    write_fields: list[str] | None = None,
) -> None:
    """Enforce model, row, and field policy separately from email or Inbox access."""
    manager = UserPolicyManager(user)
    if not manager.has_access_to_object(event, "view", fields=EVENT_PAYLOAD_FIELDS):
        raise PermissionDenied("You cannot view this calendar event.")
    if write_fields and not manager.has_access_to_object(
        event, "change", fields=write_fields
    ):
        raise PermissionDenied("You cannot change these calendar event fields.")


def _email_account(
    user: AbstractBloomerpUser, account_id: UUID, inbox_id: int
) -> EmailAccount:
    """Resolve a usable sender explicitly linked to the relevant source Inbox."""
    account = (
        accessible_email_accounts(user)
        .filter(pk=account_id, status=EmailAccount.Status.ACTIVE)
        .first()
    )
    if (
        account is None
        or not InboxFolder.objects.filter(
            inbox_id=inbox_id,
            type="email",
            related_object_id=str(account_id),
        ).exists()
    ):
        raise PermissionDenied("This email identity is not available in this Inbox.")
    return account


def _send(
    account: EmailAccount,
    event: CalendarEvent,
    method: str,
    payload: bytes,
    recipients: list[str],
) -> str:
    """Send a calendar alternative through the configured provider and Sent-copy path."""
    adapter = _resolve_email_adapter_for_account(account)
    try:
        return adapter.send_email(
            to=recipients,
            subject=f"{method}: {event.title}",
            body_text=event.title,
            body_html=f"<p>{escape(event.title)}</p>",
            attachments=[
                EmailAttachment(
                    filename="invite.ics",
                    content=payload,
                    content_type="text/calendar",
                    calendar_method=method,
                )
            ],
        )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def calendar_sender(user: AbstractBloomerpUser, event: CalendarEvent) -> EmailAccount:
    """Resolve the original sending identity without trusting changed composer values."""
    accounts = accessible_email_accounts(user).filter(email_address__iexact=event.organizer_email, status="active")
    for account in accounts:
        if InboxFolder.objects.filter(
            inbox_id=event.organizing_inbox_id, type="email", related_object_id=str(account.pk),
        ).exists():
            return account
    raise ValidationError("The original sending account is required to cancel this invitation.")


def send_removed_calendar_cancellations(*, user: AbstractBloomerpUser, event_id: UUID) -> None:
    """Deliver pending guest removals independently of general invitation-update emails."""
    event = CalendarEvent.objects.get(pk=event_id)
    account = calendar_sender(user, event)
    send_calendar_request(user=user, event_id=event.pk, email_account_id=account.pk, cancel_removed_only=True)


def _attendees(
    user: AbstractBloomerpUser, event: CalendarEvent, *, include_cancelled: bool = False,
) -> list[CalendarEventParticipant]:
    """Read invited identities, optionally including removed guests awaiting cancellation delivery."""
    manager = UserPolicyManager(user)
    attendees = list(
        (event.participants.all() if include_cancelled else event.participants.filter(invitation_cancelled=False)).select_related("user")
    )
    for participant in attendees:
        if not manager.has_access_to_object(
            participant,
            "view",
            fields=["email", "display_name", "response_status", "user"],
        ):
            raise PermissionDenied("You cannot view these attendees.")
        if not participant.email:
            if participant.user is None or not manager.has_access_to_object(
                participant.user, "view", fields=["email"]
            ):
                raise PermissionDenied("You cannot use this attendee's email identity.")
            if not manager.has_access_to_object(
                participant, "change", fields=["email"]
            ):
                raise PermissionDenied(
                    "You cannot record this attendee's invited email."
                )
            participant.email = participant.user.email
            participant.save()
        if not participant.email:
            raise ValidationError(
                "Each attendee needs an email address to receive an invitation."
            )
    return attendees


@transaction.atomic
def send_calendar_request(
    *,
    user: AbstractBloomerpUser,
    event_id: UUID,
    email_account_id: UUID,
    cancel: bool = False,
    cancel_removed_only: bool = False,
) -> str:
    """Send an explicit iTIP revision through ordinary email sending.

    Call outside an enclosing transaction or after its commit. Each successful
    send after the initial invitation advances SEQUENCE; email delivery outcomes
    and retries belong to the email infrastructure. Removed guests receive a
    targeted cancellation first; cancel_removed_only skips the remaining guests' update.
    """
    event = CalendarEvent.objects.select_for_update().get(pk=event_id)
    require_event_access(
        user,
        event,
        write_fields=[
            "sequence",
            "scheduling_dtstamp",
            "cancelled",
            "invitation_sent_at",
        ],
    )
    if event.organizing_inbox_id is None:
        raise PermissionDenied(
            "Only the organizer can send meeting updates or cancellations."
        )
    account = _email_account(user, email_account_id, event.organizing_inbox_id)
    if account.email_address.lower() != event.organizer_email.lower():
        raise ValidationError(
            "The sending email identity must match the meeting organizer."
        )
    if event.cancelled:
        raise ValidationError("This meeting is already cancelled.")
    if cancel and event.invitation_sent_at is None:
        raise ValidationError("Send an invitation before sending a cancellation.")
    all_attendees = _attendees(user, event, include_cancelled=True)
    removed = [participant for participant in all_attendees if participant.invitation_cancelled]
    if cancel_removed_only and not removed:
        return ""
    attendees = all_attendees if cancel else [participant for participant in all_attendees if not participant.invitation_cancelled]
    recipients = list(
        dict.fromkeys(
            participant.email
            for participant in attendees
            if participant.email.lower() != event.organizer_email.lower()
        )
    )
    if not recipients and not removed:
        raise ValidationError(
            "At least one explicitly invited email recipient is required."
        )
    manager = UserPolicyManager(user)
    updating = event.invitation_sent_at is not None
    if updating:
        event.sequence += 1
        if not cancel and not cancel_removed_only:
            for participant in attendees:
                if not manager.has_access_to_object(
                    participant,
                    "change",
                    fields=[
                        "response_status",
                        "responded_at",
                        "reply_sequence",
                        "reply_dtstamp",
                    ],
                ):
                    raise PermissionDenied("You cannot request new attendee responses.")
                participant.response_status = "awaiting_response"
                participant.responded_at = None
                participant.reply_sequence = None
                participant.reply_dtstamp = None
    stamp = timezone.now().replace(microsecond=0)
    if stamp <= event.scheduling_dtstamp:
        stamp = event.scheduling_dtstamp.replace(microsecond=0) + timedelta(seconds=1)
    event.scheduling_dtstamp = stamp
    method = "CANCEL" if cancel else "REQUEST"
    message_id = ""
    if removed and not cancel:
        payload = build_scheduling_calendar(event, "CANCEL", removed, stamp=stamp, cancel_entire_event=False)
        removed_recipients = list(dict.fromkeys(person.email for person in removed if person.email.lower() != event.organizer_email.lower()))
        if removed_recipients:
            message_id = _send(account, event, "CANCEL", payload, removed_recipients)
        event.participants.filter(pk__in=[person.pk for person in removed]).delete()
    if recipients and not cancel_removed_only:
        payload = build_scheduling_calendar(event, method, attendees, stamp=stamp)
        message_id = _send(account, event, method, payload, recipients)
    event.cancelled = cancel
    event.invitation_sent_at = stamp
    event.save()
    if updating and not cancel and not cancel_removed_only:
        for participant in attendees:
            participant.save()
    return message_id


@transaction.atomic
def respond_to_calendar_invitation(
    *,
    user: AbstractBloomerpUser,
    event_id: UUID,
    email_account_id: UUID | None = None,
    inbox_id: int | None = None,
    response_status: str,
    expected_sequence: int,
) -> str | None:
    """Record a response, sending an iTIP reply for an external invitation.

    Without an explicit account, resolve the caller's user or invited mailbox identity.
    Explicit email-screen responses retain the existing row and field policy checks.
    Failed delivery rolls back attendance, and repeated successful replies are suppressed.
    """
    from bloomerp.communication.utils.permissions import accessible_inboxes

    if response_status not in {"accepted", "tentative", "declined"}:
        raise ValidationError("Choose accepted, tentative, or declined.")
    event = CalendarEvent.objects.select_for_update().get(pk=event_id)
    own_response = email_account_id is None and inbox_id is None
    send_reply = True
    account = None
    if own_response:
        identity = event.get_participant(user)
        if identity is None:
            raise PermissionDenied("You are not an invited participant.")
        participant = event.participants.select_for_update().get(pk=identity.pk)
        send_reply = not bool(event.organizing_inbox_id)
        if send_reply:
            accounts = accessible_email_accounts(user).filter(
                email_address__iexact=participant.email, status="active"
            )
            for candidate in accounts:
                folder = InboxFolder.objects.filter(
                    inbox__in=event.inboxes.filter(pk__in=accessible_inboxes(user)),
                    type="email", related_object_id=str(candidate.pk),
                ).first()
                if folder is not None:
                    account = _email_account(user, candidate.pk, folder.inbox_id)
                    break
            if account is None:
                raise ValidationError("The invited email account is not available to send your response.")
    else:
        if email_account_id is None or inbox_id is None:
            raise ValidationError("Choose an invited email account and its calendar inbox.")
        require_event_access(user, event)
        account = _email_account(user, email_account_id, inbox_id)
        if not event.inboxes.filter(pk=inbox_id).exists():
            raise PermissionDenied("This event is not placed in the responding Inbox.")
        participant = event.participants.select_for_update().filter(
            email__iexact=account.email_address, invitation_cancelled=False
        ).first()
        if participant is None:
            raise PermissionDenied("This email identity was not invited to the meeting.")
        manager = UserPolicyManager(user)
        if not manager.has_access_to_object(
            participant, "change", fields=[
                "response_status", "responded_at", "reply_sequence", "reply_dtstamp",
                "last_sent_reply_sequence", "last_sent_reply_status",
            ],
        ):
            raise PermissionDenied("You cannot respond for this participant.")
        if not manager.has_access_to_object(
            participant, "view", fields=["email", "display_name", "response_status"]
        ):
            raise PermissionDenied("You cannot view this participant.")
    if event.cancelled or event.sequence != expected_sequence:
        raise ValidationError("This invitation was updated or cancelled. Refresh it before responding.")
    if participant.response_status == response_status and (
        participant.last_sent_reply_sequence == event.sequence
        and participant.last_sent_reply_status == response_status
        if send_reply else participant.reply_sequence == event.sequence
    ):
        return None
    stamp = timezone.now().replace(microsecond=0)
    if participant.reply_dtstamp and stamp <= participant.reply_dtstamp:
        stamp = participant.reply_dtstamp.replace(microsecond=0) + timedelta(seconds=1)
    message_id = None
    if send_reply:
        payload = build_scheduling_calendar(
            event, "REPLY", [participant], stamp=stamp, response_status=response_status
        )
        message_id = _send(account, event, "REPLY", payload, [event.organizer_email])
        participant.last_sent_reply_sequence = event.sequence
        participant.last_sent_reply_status = response_status
    participant.response_status = response_status
    participant.responded_at = stamp
    participant.reply_sequence = event.sequence
    participant.reply_dtstamp = stamp
    participant.save()
    return message_id
