"""Calendar MIME extraction and standards-compatible SMTP alternatives."""

from email.message import EmailMessage, Message

from bloomerp.communication.builtins.emails.base_adapter import (
    CalendarEmailPart,
    EmailAttachment,
)

MAX_CALENDAR_BYTES = 1_048_576


def extract_calendar_parts(message: Message) -> list[CalendarEmailPart]:
    """Read scheduling bodies and attachments without trusting their file names."""
    if message.get_content_maintype() == "message":
        return []
    if message.is_multipart():
        return [
            part
            for child in message.get_payload()
            for part in extract_calendar_parts(child)
        ]
    content_type = message.get_content_type().lower()
    if content_type not in {
        "text/calendar",
        "application/ics",
        "application/icalendar",
    }:
        return []
    payload = message.get_payload(decode=True) or b""
    if len(payload) > MAX_CALENDAR_BYTES:
        return [CalendarEmailPart(content="", method="INVALID")]
    try:
        content = payload.decode(message.get_content_charset() or "utf-8")
    except (UnicodeError, LookupError):
        return [CalendarEmailPart(content="", method="INVALID")]
    return [
        CalendarEmailPart(
            content=content, method=str(message.get_param("method") or "").upper()
        )
    ]


def add_calendar_alternative(
    message: EmailMessage, attachment: EmailAttachment
) -> None:
    """Attach an iMIP calendar alternative with a method matching its VCALENDAR."""
    if attachment.calendar_method not in {"REQUEST", "REPLY", "CANCEL"}:
        raise ValueError("Unsupported calendar scheduling method.")
    target = message
    if message.get_content_subtype() == "mixed":
        target = message.get_payload()[0]
    target.add_alternative(
        attachment.content.decode("utf-8"),
        subtype="calendar",
        charset="utf-8",
        params={"method": attachment.calendar_method, "component": "VEVENT"},
        disposition="inline",
        filename=attachment.filename,
    )
