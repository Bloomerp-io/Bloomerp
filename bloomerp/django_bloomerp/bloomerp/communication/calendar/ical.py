"""Parse and generate the supported single-event iTIP scheduling profile."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.validators import validate_email
from django.utils import timezone
from icalendar import Calendar, Event, vCalAddress, vText

from bloomerp.models.communication.calendar import (
    CalendarEvent,
    CalendarEventParticipant,
)

PARTSTAT_TO_STATUS = {
    "NEEDS-ACTION": "awaiting_response",
    "ACCEPTED": "accepted",
    "TENTATIVE": "tentative",
    "DECLINED": "declined",
}
STATUS_TO_PARTSTAT = {value: key for key, value in PARTSTAT_TO_STATUS.items()}


@dataclass(frozen=True)
class SchedulingMessage:
    """Validated scheduling envelope with revision and attendee identities."""

    method: str
    uid: str
    organizer: str
    sequence: int
    stamp: datetime
    attendees: tuple[tuple[str, str, str], ...]
    event: Event
    source: str


def calendar_address(value: Any) -> str:
    """Accept explicit mailto identities only, without delegated sender substitution."""
    if value is None or isinstance(value, list) or value.params.get("SENT-BY"):
        raise ValueError("Missing, repeated, or delegated calendar address.")
    text = str(value)
    if not text.lower().startswith("mailto:"):
        raise ValueError("A calendar address must use mailto.")
    address = unquote(text[7:]).strip().lower()
    validate_email(address)
    return address


def parse_scheduling_message(content: str, mime_method: str = "") -> SchedulingMessage:
    """Validate a single nonrecurring VEVENT before any database mutation."""
    calendar = Calendar.from_ical(content)
    method = str(calendar.get("METHOD", "")).upper()
    if method not in {"REQUEST", "REPLY", "CANCEL"} or (
        mime_method and mime_method != method
    ):
        raise ValueError("Unsupported or mismatched scheduling method.")
    events = calendar.walk("VEVENT")
    if len(events) != 1:
        raise ValueError(
            "Only one nonrecurring event per scheduling message is supported."
        )
    event = events[0]
    if event.errors or any(
        name in event for name in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")
    ):
        raise ValueError("Recurring or malformed scheduling messages require review.")
    for key in (
        "UID",
        "ORGANIZER",
        "SEQUENCE",
        "DTSTAMP",
        "DTSTART",
        "DTEND",
        "DURATION",
    ):
        if isinstance(event.get(key), list):
            raise TypeError(f"Repeated scheduling property: {key}.")
    uid = str(event.get("UID", "")).strip()
    if not uid or len(uid) > 255:
        raise ValueError("Missing or excessively long event UID.")
    organizer = calendar_address(event.get("ORGANIZER"))
    sequence = int(event.get("SEQUENCE", 0))
    if sequence < 0 or sequence > 2_147_483_647:
        raise ValueError("Invalid event sequence.")
    stamp = event.decoded("DTSTAMP")
    if not isinstance(stamp, datetime) or timezone.is_naive(stamp):
        raise ValueError("DTSTAMP must be an aware datetime.")
    raw_attendees = event.get("ATTENDEE", [])
    if not isinstance(raw_attendees, list):
        raw_attendees = [raw_attendees]
    attendees = []
    for value in raw_attendees:
        address = calendar_address(value)
        status = PARTSTAT_TO_STATUS.get(
            str(value.params.get("PARTSTAT", "NEEDS-ACTION")).upper()
        )
        if status is None:
            raise ValueError("Unsupported attendee participation status.")
        attendees.append((address, status, str(value.params.get("CN", ""))[:255]))
    if len({attendee[0] for attendee in attendees}) != len(attendees):
        raise ValueError("Repeated attendee identity.")
    if method == "REPLY" and (
        len(attendees) != 1 or attendees[0][1] == "awaiting_response"
    ):
        raise ValueError("A reply must contain exactly one responding attendee.")
    if method == "REQUEST" and not attendees:
        raise ValueError("A scheduling request needs attendees.")
    return SchedulingMessage(
        method,
        uid,
        organizer,
        sequence,
        stamp.astimezone(UTC),
        tuple(attendees),
        event,
        content,
    )


def event_values(message: SchedulingMessage) -> dict[str, Any]:
    """Resolve aware instants or exclusive date ranges without guessing floating time."""
    component = message.event
    start = component.decoded("DTSTART")
    end = component.decoded("DTEND") if "DTEND" in component else None
    if "DURATION" in component:
        if end is not None:
            raise ValueError("Specify DTEND or DURATION, not both.")
        end = start + component.decoded("DURATION")
    values: dict[str, Any] = {
        "title": str(component.get("SUMMARY", ""))[:255] or "(Untitled meeting)",
        "content": str(component.get("DESCRIPTION", "")),
        "location": str(component.get("LOCATION", ""))[:255],
        "start": None,
        "end": None,
        "event_timezone": None,
        "start_date": None,
        "end_date": None,
    }
    if isinstance(start, datetime):
        if (
            not isinstance(end, datetime)
            or timezone.is_naive(start)
            or timezone.is_naive(end)
        ):
            raise ValueError(
                "Timed invitations require resolvable timezone-aware start and end."
            )
        zone = (
            getattr(start.tzinfo, "key", None)
            or getattr(start.tzinfo, "zone", None)
            or "UTC"
        )
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = "UTC"
        values.update(
            all_day=False,
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
            event_timezone=zone,
        )
        if values["end"] <= values["start"]:
            raise ValueError("Meeting end must be after start.")
    elif isinstance(start, date):
        end = end or start + timedelta(days=1)
        if not isinstance(end, date) or isinstance(end, datetime) or end <= start:
            raise ValueError("Invalid all-day date range.")
        values.update(all_day=True, start_date=start, end_date=end)
    else:
        raise TypeError("Missing or invalid DTSTART.")
    return values


def build_scheduling_calendar(
    event: CalendarEvent,
    method: str,
    attendees: list[CalendarEventParticipant],
    *,
    stamp: datetime,
    response_status: str | None = None,
    cancel_entire_event: bool = True,
) -> bytes:
    """Emit scheduling properties, distinguishing attendee removal from whole-event cancellation."""
    calendar = Calendar()
    calendar.add("PRODID", "-//Bloomerp//Calendar scheduling//EN")
    calendar.add("VERSION", "2.0")
    calendar.add("METHOD", method)
    component = Event()
    component.add("UID", event.calendar_uid)
    component.add("SEQUENCE", event.sequence)
    component.add("DTSTAMP", stamp.astimezone(UTC))
    component.add("ORGANIZER", vCalAddress(f"mailto:{event.organizer_email}"))
    component.add("SUMMARY", event.title)
    component.add("DESCRIPTION", event.content)
    component.add("LOCATION", event.location)
    component.add(
        "DTSTART", event.start_date if event.all_day else event.start.astimezone(UTC)
    )
    component.add(
        "DTEND", event.end_date if event.all_day else event.end.astimezone(UTC)
    )
    if method == "CANCEL" and cancel_entire_event:
        component.add("STATUS", "CANCELLED")
    for participant in attendees:
        if not participant.email:
            raise ValueError("Each emailed attendee needs an invited email address.")
        address = vCalAddress(f"mailto:{participant.email}")
        status = response_status or participant.response_status
        address.params["PARTSTAT"] = STATUS_TO_PARTSTAT[status]
        if method == "REQUEST":
            address.params["RSVP"] = (
                "TRUE" if status == "awaiting_response" else "FALSE"
            )
        if participant.display_name:
            address.params["CN"] = vText(participant.display_name)
        component.add("ATTENDEE", address)
    calendar.add_component(component)
    return calendar.to_ical()
