"""Signer inputs and drawn-stroke validation shared by PDF overlays and completion."""

from collections.abc import Sequence
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bloomerp.models.document_signing import SignatureRecipient, SignatureRequestField
from bloomerp.models.document_signing.definition import (
    DrawnSignature,
    SignatureFieldType,
    validate_drawn_signature,
)
from bloomerp.widgets.drawn_signature import DrawnSignatureWidget

SIGNING_CONSENT = _("I agree to sign this document electronically.")


class DrawnSignatureFormField(forms.JSONField):
    """Accept handwriting strokes while rejecting typed names and empty drawings."""

    def clean(self, value: Any) -> DrawnSignature | None:
        """Parse the hidden JSON value and validate its visible, bounded ink strokes."""
        value = super().clean(value)
        return None if value is None else validate_drawn_signature(value)


def signing_input(field: SignatureRequestField) -> forms.Field:
    """Choose a server-validated input for one immutable request field."""
    label = str(field.settings.get("label") or field.get_field_type_display())
    attrs = {"class": "sign-document__control bg-transparent", "aria-label": label}
    kwargs = {"label": label, "required": field.required}
    if field.field_type == SignatureFieldType.SIGNATURE:
        return DrawnSignatureFormField(
            **kwargs,
            widget=DrawnSignatureWidget(attrs={"aria-label": label}),
        )
    if field.field_type == SignatureFieldType.CHECKBOX:
        return forms.BooleanField(
            required=False, label=label, widget=forms.CheckboxInput(attrs=attrs)
        )
    if field.field_type in {SignatureFieldType.RADIO, SignatureFieldType.SELECTION}:
        options = field.settings.get("options", [])
        if (
            not isinstance(options, list)
            or not options
            or any(
                not isinstance(option, str) or not option.strip() for option in options
            )
        ):
            raise ValidationError(
                f"{label}: add choices in the signing preparation before signing."
            )
        choices = [(str(option), str(option)) for option in options]
        widget = (
            forms.RadioSelect(attrs=attrs)
            if field.field_type == SignatureFieldType.RADIO
            else forms.Select(attrs=attrs)
        )
        if field.field_type == SignatureFieldType.SELECTION:
            choices = [("", _("Choose…")), *choices]
        return forms.ChoiceField(**kwargs, choices=choices, widget=widget)
    if field.field_type == SignatureFieldType.EMAIL:
        return forms.EmailField(**kwargs, widget=forms.EmailInput(attrs=attrs))
    if field.field_type == SignatureFieldType.DATE:
        return forms.DateField(
            **kwargs,
            widget=forms.DateInput(attrs={**attrs, "type": "date"}, format="%Y-%m-%d"),
        )
    if field.field_type == SignatureFieldType.MULTILINE_TEXT:
        return forms.CharField(
            **kwargs, max_length=10000, widget=forms.Textarea(attrs=attrs)
        )
    if field.field_type == SignatureFieldType.INITIALS:
        attrs["placeholder"] = str(_("Initials"))
        attrs["class"] += " sign-document__signature"
    return forms.CharField(
        **kwargs, max_length=2000, widget=forms.TextInput(attrs=attrs)
    )


class SignDocumentForm(forms.Form):
    """Validate every assigned input and explicit consent before recording a signature."""

    consent = forms.BooleanField(
        label=SIGNING_CONSENT,
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-primary"}),
    )

    def __init__(
        self,
        *,
        recipient: SignatureRecipient,
        placements: Sequence[SignatureRequestField],
        **kwargs: Any,
    ) -> None:
        """Build controls from the stored request snapshot rather than client-supplied definitions."""
        super().__init__(**kwargs)
        self.signing_fields: list[tuple[SignatureRequestField, forms.BoundField]] = []
        defaults = {
            SignatureFieldType.NAME: recipient.name,
            SignatureFieldType.EMAIL: recipient.email,
            SignatureFieldType.DATE: timezone.localdate().isoformat(),
        }
        for placement in placements:
            name = f"field_{placement.pk.hex}"
            self.fields[name] = signing_input(placement)
            self.initial[name] = (
                placement.value
                if placement.value is not None
                else defaults.get(placement.field_type, "")
            )
            self.signing_fields.append((placement, self[name]))

    def values(self) -> dict[str, str | bool | DrawnSignature | None]:
        """Return normalized, JSON-safe values keyed by the actual request-field IDs."""
        values: dict[str, str | bool | DrawnSignature | None] = {}
        for placement, field in self.signing_fields:
            value = self.cleaned_data[field.name]
            if placement.field_type == SignatureFieldType.DATE and value:
                value = value.isoformat()
            values[str(placement.pk)] = value if value != "" else None
        return values
