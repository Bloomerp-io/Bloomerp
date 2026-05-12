import re

from django import forms

from bloomerp.widgets.phone_number_widget import PhoneNumberWidget


PHONE_NUMBER_ALLOWED_CHARS_RE = re.compile(r"^\+?[0-9\s().-]+$")


def normalize_phone_number(value: str) -> str:
    value = value.strip()
    if not value:
        return value

    if value.count("+") > 1 or ("+" in value and not value.startswith("+")):
        raise forms.ValidationError("Enter a valid phone number.")

    if not PHONE_NUMBER_ALLOWED_CHARS_RE.match(value):
        raise forms.ValidationError("Enter a valid phone number.")

    normalized = re.sub(r"[\s().-]+", "", value)
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"

    digits = normalized[1:] if normalized.startswith("+") else normalized
    if not digits.isdigit() or not 4 <= len(digits) <= 15:
        raise forms.ValidationError("Enter a valid phone number.")

    return normalized


class PhoneNumberFormField(forms.CharField):
    """Form field that accepts local numbers and international country codes."""

    widget = PhoneNumberWidget

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return value
        return normalize_phone_number(value)
