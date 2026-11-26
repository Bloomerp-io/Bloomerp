"""JSON representation of a booking link's local availability schedule."""

from datetime import date, time
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


class Weekday(StrEnum):
    """Stable keys for the seven days in a repeating schedule."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class AvailabilityInterval(BaseModel):
    """An ordered pair of wall-clock times on a single local date."""

    model_config = ConfigDict(extra="forbid")

    start: time
    end: time

    @field_validator("start", "end")
    @classmethod
    def validate_local_minute(cls, value: time) -> time:
        """Keep times local with the same precision as the booking editor."""
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("Use a local time in hours and minutes.")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Reject inverted and empty time windows."""
        if self.end <= self.start:
            raise ValueError("End time must be after start time.")
        return self

    @field_serializer("start", "end", when_used="json")
    def serialize_local_minute(self, value: time) -> str:
        """Store each time with hours and minutes for the browser editor."""
        return value.isoformat(timespec="minutes")


def ordered_intervals(intervals: list[AvailabilityInterval]) -> list[AvailabilityInterval]:
    """Sort a day's windows and reject overlaps while allowing adjacent windows."""
    ordered = sorted(intervals, key=interval_start)
    if any(second.start < first.end for first, second in zip(ordered, ordered[1:])):
        raise ValueError("Hours for the same day must not overlap.")
    return ordered


def interval_start(interval: AvailabilityInterval) -> time:
    """Return the beginning of an interval for chronological ordering."""
    return interval.start


DayHours = Annotated[list[AvailabilityInterval], AfterValidator(ordered_intervals)]


class AvailabilityException(BaseModel):
    """Replace weekly hours for one date, with empty hours closing the day."""

    model_config = ConfigDict(extra="forbid")

    date: date
    hours: DayHours = Field(default_factory=list)


class BookingLinkAvailability(BaseModel):
    """Serialize inclusive date bounds, repeating hours and date-specific overrides."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    days: dict[Weekday, DayHours] = Field(default_factory=dict)
    exceptions: list[AvailabilityException] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def read_flat_weekdays(cls, value: object) -> object:
        """Read weekday-only maps entered before the structured editor existed."""
        if isinstance(value, dict) and value and set(value) <= set(Weekday):
            return {"days": value}
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """Check chronological bounds and allow at most one override per date."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date.")
        dates = {exception.date for exception in self.exceptions}
        if len(dates) != len(self.exceptions):
            raise ValueError("Use only one override for each date.")
        return self

    def hours_on(self, day: date) -> list[AvailabilityInterval]:
        """Resolve local hours, applying date bounds before date-specific hours."""
        if (self.start_date and day < self.start_date) or (self.end_date and day > self.end_date):
            return []
        for exception in self.exceptions:
            if exception.date == day:
                return exception.hours
        return self.days.get(tuple(Weekday)[day.weekday()], [])
