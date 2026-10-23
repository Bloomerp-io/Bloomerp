"""Permission-checked scheduling actions using existing inbox email identities."""

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from hashlib import sha256
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape
from icalendar import Calendar, vCalAddress

from bloomerp.communication.builtins.emails.actions import (
    _resolve_email_adapter_for_account,
)
from bloomerp.communication.builtins.emails.base_adapter import (
    EmailAttachment,
    EmailSendResult,
    EmailSendUnconfirmed,
)
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.communication.builtins.emails.sending import (
    UNCONFIRMED_SEND_MESSAGE,
    outbound_message_id,
    store_outbound_email,
)
from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarEventParticipant,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
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

@dataclass(frozen=True)
class _CalendarDelivery:
    """Retain an uncertain provider identity independently of rolled-back event changes."""

    account_id: UUID
    event_id: UUID
    result: str | EmailSendResult
    operation_key: str
    subject: str
    body_html: str
    recipients: list[str]
    pending: bool = False


_calendar_deliveries: ContextVar[list[_CalendarDelivery] | None] = ContextVar(
    "calendar_deliveries", default=None,
)
_calendar_locked_account: ContextVar[UUID | None] = ContextVar(
    "calendar_locked_account", default=None,
)


class CalendarSendUnconfirmed(ValidationError):
    """Expose a safe delivery warning while carrying reconciliation data across transactions."""

    def __init__(self, delivery: _CalendarDelivery | None = None) -> None:
        """Keep transport identifiers internal and present only an actionable delivery warning."""
        self.delivery = delivery
        super().__init__(str(UNCONFIRMED_SEND_MESSAGE))


def preserve_calendar_delivery[**SendParameters, SendReturn](
    operation: Callable[SendParameters, SendReturn],
) -> Callable[SendParameters, SendReturn]:
    """Retain delivery checkpoints while locking the sender before the scheduling event."""

    @wraps(operation)
    def wrapped(*args: SendParameters.args, **kwargs: SendParameters.kwargs) -> SendReturn:
        """Save the remote send identity after the scheduling savepoint has rolled back."""
        deliveries = _calendar_deliveries.get()
        token = None
        account_token = None
        account_id = None
        if deliveries is None:
            snapshot = CalendarEvent.objects.get(pk=kwargs["event_id"])
            local_response = (
                "response_status" in kwargs
                and kwargs.get("email_account_id") is None
                and kwargs.get("inbox_id") is None
                and snapshot.organizing_inbox_id is not None
            )
            if not local_response:
                account_id = _calendar_delivery_account_id(
                    kwargs["user"], snapshot, kwargs.get("email_account_id"),
                )
            if account_id is not None:
                _prepare_calendar_authorization(kwargs["user"], account_id)
            deliveries = []
            token = _calendar_deliveries.set(deliveries)
        try:
            with transaction.atomic():
                if token is not None:
                    if account_id is not None:
                        locked = EmailAccount.objects.select_for_update().filter(pk=account_id).first()
                        account_id = locked.pk if locked is not None else None
                    account_token = _calendar_locked_account.set(account_id)
                CalendarEvent.objects.select_for_update().get(pk=kwargs["event_id"])
                try:
                    with transaction.atomic():
                        return operation(*args, **kwargs)
                except Exception as error:  # noqa: BLE001 - retain remote deliveries before re-raising.
                    failure = error
                for delivery in deliveries:
                    account = EmailAccount.objects.get(pk=delivery.account_id)
                    items = store_outbound_email(
                        account=account,
                        result=delivery.result,
                        form_data={"to": delivery.recipients, "subject": delivery.subject},
                        body_html=delivery.body_html,
                        pending=delivery.pending,
                    )
                    for item in items:
                        item.raw_meta_data.update(
                            calendar_event_id=str(delivery.event_id),
                            calendar_send_key=delivery.operation_key,
                        )
                        item.save(update_fields=["raw_meta_data"])
            raise failure
        finally:
            if account_token is not None:
                _calendar_locked_account.reset(account_token)
            if token is not None:
                _calendar_deliveries.reset(token)

    return wrapped


def _invited_email_account(
    user: AbstractBloomerpUser, event: CalendarEvent, participant: CalendarEventParticipant,
) -> EmailAccount | None:
    """Resolve the invited mailbox consistently before locking and when validating a reply."""
    from bloomerp.communication.utils.permissions import accessible_inboxes

    accounts = accessible_email_accounts(user).filter(
        email_address__iexact=participant.email, status="active",
    ).order_by("pk")
    for candidate in accounts:
        folder = InboxFolder.objects.filter(
            inbox__in=event.inboxes.filter(pk__in=accessible_inboxes(user)),
            type="email", related_object_id=str(candidate.pk),
        ).first()
        if folder is not None:
            return _email_account(user, candidate.pk, folder.inbox_id)
    return None


def _calendar_delivery_account_id(
    user: AbstractBloomerpUser, event: CalendarEvent, explicit_account_id: UUID | None,
) -> UUID | None:
    """Choose a candidate sender before event locking, leaving authorization to the operation."""
    if explicit_account_id is not None:
        account = accessible_email_accounts(user).filter(
            pk=explicit_account_id, status="active",
        ).first()
        return account.pk if account is not None else None
    if event.organizing_inbox_id is not None:
        if event.cancelled or event.invitation_sent_at is None or not event.participants.exclude(
            email="",
        ).exclude(email__iexact=event.organizer_email).exists():
            return None
        try:
            return calendar_sender(user, event).pk
        except ValidationError:
            return None
    participant = event.get_participant(user)
    account = _invited_email_account(user, event, participant) if participant is not None else None
    return account.pk if account is not None else None


def _prepare_calendar_authorization(user: AbstractBloomerpUser, account_id: UUID | None) -> None:
    """Persist provider authorization before scheduling savepoints can roll back local changes."""
    if account_id is None:
        return
    account = accessible_email_accounts(user).filter(pk=account_id, status="active").first()
    if account is None:
        return
    provider = EMAIL_PROVIDER_REGISTRY.get(account.provider)
    if provider is None or provider.authorization is None or provider.authorization.prepare is None:
        return
    adapter = provider.adapter_class(account)
    try:
        provider.authorization.prepare(adapter)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def _remember_calendar_delivery(
    account: EmailAccount, event: CalendarEvent, result: str | EmailSendResult,
    operation_key: str, method: str, recipients: list[str], *, pending: bool = False,
) -> _CalendarDelivery:
    """Keep completed sends available if a later message in this scheduling action fails."""
    delivery = _CalendarDelivery(
        account_id=account.pk, event_id=event.pk, result=result,
        operation_key=operation_key, subject=f"{method}: {event.title}",
        body_html=f"<p>{escape(event.title)}</p>", recipients=recipients,
        pending=pending,
    )
    deliveries = _calendar_deliveries.get()
    if deliveries is not None:
        deliveries.append(delivery)
    return delivery


def _calendar_send_key(
    account: EmailAccount, event: CalendarEvent, method: str, payload: bytes,
    recipients: list[str],
) -> str:
    """Identify one calendar revision and recipient set without a retry's new timestamp."""
    calendar = Calendar.from_ical(payload)
    for component in calendar.walk():
        component.pop("DTSTAMP", None)
        attendees = component.get("ATTENDEE")
        if isinstance(attendees, list):
            component["ATTENDEE"] = sorted(attendees, key=_calendar_attendee_key)
    identity = [
        str(account.pk).encode(), str(event.pk).encode(), method.encode(),
        "\n".join(sorted(address.lower() for address in recipients)).encode(),
        calendar.to_ical(),
    ]
    return sha256(b"\0".join(identity)).hexdigest()


def _calendar_attendee_key(attendee: vCalAddress) -> tuple[bytes, bytes]:
    """Canonicalize repeated attendee properties while preserving meaningful parameters."""
    return attendee.to_ical().lower(), attendee.params.to_ical()


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
    if account.pk != _calendar_locked_account.get():
        raise ValidationError("The sending account changed. Refresh this event before sending again.")
    operation_key = _calendar_send_key(account, event, method, payload, recipients)
    previous_deliveries = list(InboxItem.objects.filter(
        item_type="email",
        folder__type="email",
        folder__related_object_id=str(account.pk),
        raw_meta_data__calendar_event_id=str(event.pk),
    ).values_list("raw_meta_data", flat=True))
    if any(metadata.get("outbound_send_pending") for metadata in previous_deliveries):
        raise CalendarSendUnconfirmed()
    confirmed = next(
        (metadata for metadata in previous_deliveries if metadata.get("calendar_send_key") == operation_key),
        None,
    )
    if confirmed is not None:
        return str(confirmed.get("message_id") or "")
    adapter = _resolve_email_adapter_for_account(account)
    try:
        result = adapter.send_email(
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
        _remember_calendar_delivery(account, event, result, operation_key, method, recipients)
        return outbound_message_id(result)
    except EmailSendUnconfirmed as exc:
        delivery = _remember_calendar_delivery(
            account, event, exc.result, operation_key, method, recipients, pending=True,
        )
        raise CalendarSendUnconfirmed(delivery) from exc
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


def calendar_sender(user: AbstractBloomerpUser, event: CalendarEvent) -> EmailAccount:
    """Resolve the original sending identity without trusting changed composer values."""
    accounts = accessible_email_accounts(user).filter(email_address__iexact=event.organizer_email, status="active").order_by("pk")
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


@preserve_calendar_delivery
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


@preserve_calendar_delivery
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
            account = _invited_email_account(user, event, participant)
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
