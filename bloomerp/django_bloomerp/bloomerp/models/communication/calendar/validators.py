"""Validate timezone identifiers used by timed events and booking availability."""

from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_calendar_timezone(value: str) -> None:
    """Require a resolvable IANA timezone instead of guessing a source timezone."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(
            _("Enter a valid IANA timezone."), code="invalid_timezone"
        ) from exc


def new_calendar_uid() -> str:
    """Generate a stable, globally unique scheduling identity for a local meeting."""
    return f"{uuid4()}@bloomerp"
