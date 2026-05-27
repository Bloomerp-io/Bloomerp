import re
from dataclasses import dataclass
from datetime import date

from django import forms

from bloomerp.widgets.week_widget import WeekWidget


WEEK_VALUE_RE = re.compile(r"^(\d{4})-W(\d{2})$")


@dataclass(frozen=True)
class WeekValue:
    year: int
    week: int

    def __post_init__(self):
        try:
            date.fromisocalendar(self.year, self.week, 1)
        except ValueError:
            raise forms.ValidationError("Enter a valid week.")

    def __str__(self) -> str:
        return f"{self.year:04d}-W{self.week:02d}"

    def __len__(self) -> int:
        return len(str(self))


def normalize_week_value(value):
    if value in forms.Field.empty_values:
        return value

    if isinstance(value, WeekValue):
        return value

    if not isinstance(value, str):
        raise forms.ValidationError("Enter a valid week.")

    match = WEEK_VALUE_RE.match(value.strip())
    if match is None:
        raise forms.ValidationError("Enter a valid week in YYYY-Www format.")

    return WeekValue(year=int(match.group(1)), week=int(match.group(2)))


class WeekFormField(forms.CharField):
    widget = WeekWidget

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return normalize_week_value(value)

    def prepare_value(self, value):
        if value in self.empty_values:
            return value
        return str(value)
