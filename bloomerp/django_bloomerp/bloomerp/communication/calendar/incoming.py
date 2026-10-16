"""Apply validated calendar scheduling messages during email synchronization."""

import hashlib
import logging
from email.utils import getaddresses

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from bloomerp.communication.builtins.emails.base_adapter import BloomerpEmail
from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarEventParticipant,
    CalendarSchedulingCancellation,
)
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem

from .ical import SchedulingMessage, event_values, parse_scheduling_message

logger = logging.getLogger(__name__)


def sender_address(sender: str) -> str:
    """Require exactly one sender address before trusting calendar identity claims."""
    addresses = getaddresses([sender])
    if len(addresses) != 1 or not addresses[0][1]:
        raise ValueError("A scheduling message needs exactly one email sender.")
    return addresses[0][1].strip().lower()


def _participant_for_address(
    event: CalendarEvent, address: str, name: str
) -> CalendarEventParticipant:
    """Reuse invited email or known user identity without inferring inbox attendees."""
    participant = event.participants.filter(email__iexact=address).first()
    if participant is not None:
        return participant
    users = list(get_user_model().objects.filter(email__iexact=address)[:2])
    user = users[0] if len(users) == 1 else None
    if user is not None:
        participant = event.participants.filter(user=user).first()
        if participant is not None:
            if not participant.email:
                participant.email = address
                participant.save()
            return participant
    return CalendarEventParticipant.objects.create(
        event=event, user=user, email=address, display_name=name
    )


def _apply_reply(
    message: SchedulingMessage, event: CalendarEvent, account: EmailAccount
) -> str:
    """Update only an existing invited attendee of this local organizer's revision."""
    if (
        not event.organizing_inbox_id
        or account.email_address.lower() != event.organizer_email.lower()
    ):
        return "unmatched_reply"
    if event.cancelled or message.sequence != event.sequence:
        return "stale_reply"
    address, status, _ = message.attendees[0]
    participant = (
        event.participants.select_for_update().filter(email__iexact=address).first()
    )
    if participant is None or participant.invitation_cancelled:
        return "unmatched_reply"
    if (
        participant.reply_sequence == message.sequence
        and participant.reply_dtstamp
        and participant.reply_dtstamp >= message.stamp
    ):
        return "duplicate_or_stale_reply"
    participant.response_status = status
    participant.responded_at = message.stamp
    participant.reply_sequence = message.sequence
    participant.reply_dtstamp = message.stamp
    participant.save()
    return "replied"


def _attendee_cancelled_at_revision(message: SchedulingMessage, address: str) -> bool:
    """Retain an attendee cancellation even when another account imports the meeting first."""
    tombstones = CalendarSchedulingCancellation.objects.filter(
        calendar_uid=message.uid,
        organizer_email=message.organizer,
        attendee_email__in=["", address],
    )
    return any(
        (row.sequence, row.dtstamp) >= (message.sequence, message.stamp)
        for row in tombstones
    )


def _apply_request(
    message: SchedulingMessage, event: CalendarEvent, newer: bool
) -> str:
    """Update one shared meeting and independently retain explicit attendee records."""
    if not newer:
        return "duplicate_request"
    previous_sequence = event.sequence
    for field, value in event_values(message).items():
        setattr(event, field, value)
    event._applying_scheduling_message = True
    event.sequence = message.sequence
    event.scheduling_dtstamp = message.stamp
    event.cancelled = False
    event.source_calendar = message.source
    event.save()
    invited_addresses = {attendee[0] for attendee in message.attendees}
    for participant in event.participants.exclude(email__in=invited_addresses):
        participant.invitation_cancelled = True
        participant.save()
    for address, _, name in message.attendees:
        participant = _participant_for_address(event, address, name)
        participant.invitation_cancelled = _attendee_cancelled_at_revision(
            message, address
        )
        if message.sequence > previous_sequence:
            participant.response_status = "awaiting_response"
            participant.responded_at = None
            participant.reply_sequence = None
            participant.reply_dtstamp = None
        participant.save()
    return "requested"


def _apply_cancel(message: SchedulingMessage, event: CalendarEvent) -> str:
    """Cancel a whole meeting or the listed attendees without inventing a new event."""
    addresses = {attendee[0] for attendee in message.attendees}
    if not addresses or str(message.event.get("STATUS", "")).upper() == "CANCELLED":
        event.cancelled = True
    for participant in event.participants.all():
        if not addresses or participant.email.lower() in addresses:
            participant.invitation_cancelled = True
            participant.save()
    event._applying_scheduling_message = True
    event.sequence = message.sequence
    event.scheduling_dtstamp = message.stamp
    event.source_calendar = message.source
    event.save()
    return "cancelled"


def _lock_calendar_identity(message: SchedulingMessage) -> None:
    """Serialize same-UID imports across accounts on PostgreSQL, including tombstones."""
    if connection.vendor == "postgresql":
        digest = hashlib.sha256(f"{message.uid}\0{message.organizer}".encode()).digest()
        key = int.from_bytes(digest[:8], byteorder="big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
    # SQLite's enclosing email-index write transaction already serializes writers.


@transaction.atomic
def apply_scheduling_message(
    message: SchedulingMessage,
    *,
    email: BloomerpEmail,
    folder: InboxFolder,
    account: EmailAccount,
) -> tuple[CalendarEvent | None, str]:
    """Match sender, connected recipient, organizer, UID, and revision before writing."""
    sender = sender_address(email.sender)
    expected_sender = (
        message.attendees[0][0] if message.method == "REPLY" else message.organizer
    )
    if sender != expected_sender:
        raise ValueError("The email sender does not match its scheduling identity.")
    _lock_calendar_identity(message)
    event = (
        CalendarEvent.objects.select_for_update()
        .filter(
            calendar_uid=message.uid,
            organizer_email__iexact=message.organizer,
        )
        .first()
    )
    if message.method == "REPLY":
        if event is None:
            return None, "unmatched_reply"
        outcome = _apply_reply(message, event, account)
        return (
            event if outcome in {"replied", "duplicate_or_stale_reply"} else None
        ), outcome
    recipient = account.email_address.lower()
    addresses = {attendee[0] for attendee in message.attendees}
    if message.method == "REQUEST" and recipient not in addresses:
        return None, "not_invited"
    if event is not None and event.organizing_inbox_id:
        if (
            message.method == "REQUEST"
            and message.sequence == event.sequence
            and message.stamp == event.scheduling_dtstamp
            and event.participants.filter(
                email__iexact=recipient, invitation_cancelled=False
            ).exists()
        ):
            event.inboxes.add(folder.inbox.effective_preference)
            return event, "local_invitation"
        return None, "local_organizer_echo"
    if (
        event is not None
        and message.method == "CANCEL"
        and not event.participants.filter(email__iexact=recipient).exists()
    ):
        return None, "not_invited"
    if message.method == "CANCEL":
        recipients = {
            address.lower() for _, address in getaddresses([*email.to, *email.cc])
        }
        whole_cancel = (
            not addresses or str(message.event.get("STATUS", "")).upper() == "CANCELLED"
        )
        if not whole_cancel and recipient not in addresses:
            return None, "not_invited"
        if event is None and not addresses and recipient not in recipients:
            return None, "not_invited"
        cancelled_identities = (
            {""}
            if not addresses
            or str(message.event.get("STATUS", "")).upper() == "CANCELLED"
            else addresses
        )
        for address in cancelled_identities:
            tombstone, _ = (
                CalendarSchedulingCancellation.objects.select_for_update().get_or_create(
                    calendar_uid=message.uid,
                    organizer_email=message.organizer,
                    attendee_email=address,
                    defaults={"sequence": message.sequence, "dtstamp": message.stamp},
                )
            )
            if (message.sequence, message.stamp) > (
                tombstone.sequence,
                tombstone.dtstamp,
            ):
                tombstone.sequence = message.sequence
                tombstone.dtstamp = message.stamp
                tombstone.save()
    else:
        tombstones = CalendarSchedulingCancellation.objects.filter(
            calendar_uid=message.uid,
            organizer_email=message.organizer,
            attendee_email__in=["", recipient],
        )
        if any(
            (row.sequence, row.dtstamp) >= (message.sequence, message.stamp)
            for row in tombstones
        ):
            return None, "cancelled_revision"
    if event is None:
        if message.method == "CANCEL":
            return None, "retained_cancellation"
        values = event_values(message)
        try:
            with transaction.atomic():
                event, created = (
                    CalendarEvent.objects.select_for_update().get_or_create(
                        calendar_uid=message.uid,
                        organizer_email=message.organizer,
                        defaults={
                            **values,
                            "scheduling_dtstamp": message.stamp,
                            "sequence": message.sequence,
                            "source_calendar": message.source,
                        },
                    )
                )
        except (ValidationError, IntegrityError):
            # Another connected account may have imported the shared UID first.
            event = (
                CalendarEvent.objects.select_for_update()
                .filter(
                    calendar_uid=message.uid,
                    organizer_email__iexact=message.organizer,
                )
                .first()
            )
            if event is None:
                raise
            created = False
        if created:
            for address, _, name in message.attendees:
                participant = _participant_for_address(event, address, name)
                if _attendee_cancelled_at_revision(message, address):
                    participant.invitation_cancelled = True
                    participant.save()
            event.inboxes.add(folder.inbox.effective_preference)
            return event, "created"
    known_recipient = event.participants.filter(email__iexact=recipient).exists()
    if message.method == "CANCEL" and (
        not known_recipient or (not whole_cancel and recipient not in addresses)
    ):
        return None, "not_invited"
    current_revision = (event.sequence, event.scheduling_dtstamp)
    incoming_revision = (message.sequence, message.stamp)
    if incoming_revision < current_revision:
        return None, "stale_message"
    if message.method == "CANCEL":
        outcome = _apply_cancel(message, event)
    else:
        if event.cancelled and incoming_revision == current_revision:
            return None, "stale_message"
        if incoming_revision == current_revision and not known_recipient:
            return None, "not_invited"
        outcome = _apply_request(message, event, incoming_revision > current_revision)
        event.inboxes.add(folder.inbox.effective_preference)
    return event, outcome


def process_calendar_email(
    email: BloomerpEmail, folder: InboxFolder, item: InboxItem
) -> None:
    """Isolate invalid calendar content so an ordinary inbox sync still completes."""
    if not email.calendar_parts:
        return
    account = EmailAccount.objects.get(pk=folder.related_object_id)
    results = []
    for part in email.calendar_parts:
        try:
            message = parse_scheduling_message(part.content, part.method)
            event, outcome = apply_scheduling_message(
                message, email=email, folder=folder, account=account
            )
            result = {"outcome": outcome, "method": message.method}
            if event is not None:
                result["event_id"] = str(event.pk)
                result["sequence"] = event.sequence
            results.append(result)
        except (
            ValueError,
            ValidationError,
            KeyError,
            TypeError,
            OverflowError,
            UnicodeError,
            IntegrityError,
        ) as exc:
            logger.warning(
                "Calendar message on inbox item %s requires review: %s",
                item.pk,
                type(exc).__name__,
            )
            results.append({"outcome": "requires_review", "reason": str(exc)[:500]})
    metadata = dict(item.raw_meta_data or {})
    metadata["calendar_processing"] = results
    item.raw_meta_data = metadata
    item.save(update_fields=["raw_meta_data"])
