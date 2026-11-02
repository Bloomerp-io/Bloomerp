"""Resolved PDF fields and values belonging to one request recipient."""

from datetime import date
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel, signing_builder_config
from .definition import SignatureFieldType, validate_drawn_signature
from .positioned_field import PositionedSignatureField
from .signature_recipient import SignatureRecipient


class SignatureRequestField(PositionedSignatureField):
    """Retain a concrete placement independently of subsequent reusable layout edits."""

    bloomerp_config = signing_builder_config()

    request_bound = True
    immutable_fields = ("request_id",)
    request = models.ForeignKey(
        "bloomerp.SignatureRequest",
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name=_("Request"),
    )
    recipient = models.ForeignKey(
        "bloomerp.SignatureRecipient",
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name=_("Recipient"),
    )
    value = models.JSONField(_("Value"), null=True, blank=True)
    filled_at = models.DateTimeField(_("Filled at"), null=True, blank=True)

    class Meta(PositionedSignatureField.Meta):
        verbose_name = _("Signature request field")
        verbose_name_plural = _("Signature request fields")
        ordering = ("page_number", "y", "x", "key")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            *PositionedSignatureField.Meta.constraints,
            models.UniqueConstraint(
                fields=["request", "key"], name="signature_request_field_key_unique"
            ),
        ]

    @property
    def has_value(self) -> bool:
        """Recognize a completed input while retaining false as a checkbox response."""
        return (
            self.value is not None
            and self.value != ""
            and self.value != {}
            and self.value != []
        )

    def validate_previous(self, previous: SigningModel) -> None:
        """Freeze dispatched placements and responses already accepted by a signer."""
        super().validate_previous(previous)
        request = self.get_request()
        if request is not None and request.status != "draft":
            self.require_unchanged(
                previous,
                (
                    "recipient_id",
                    "key",
                    "field_type",
                    "required",
                    "page_number",
                    "x",
                    "y",
                    "width",
                    "height",
                    "settings",
                ),
            )
        recipient = (
            SignatureRecipient.objects.using(self._state.db)
            .filter(pk=previous.recipient_id)
            .first()
        )
        if (request is not None and request.status not in {"draft", "sent"}) or (
            recipient is not None and recipient.status in {"signed", "declined"}
        ):
            self.require_unchanged(previous, ("value", "filled_at"))

    def clean(self) -> None:
        """Require same-request ownership and values compatible with the field type."""
        super().clean()
        request = self.get_request()
        recipient = (
            SignatureRecipient.objects.using(self._state.db)
            .filter(pk=self.recipient_id)
            .first()
        )
        if recipient is not None and recipient.request_id != self.request_id:
            raise ValidationError(
                {"recipient": _("The recipient must belong to this request.")}
            )
        exists = type(self).objects.using(self._state.db).filter(pk=self.pk).exists()
        if not exists and request is not None and request.status != "draft":
            raise ValidationError(
                {"request": _("Add fields while the request is a draft.")}
            )
        if self.value is None:
            if self.filled_at is not None:
                raise ValidationError(
                    {"filled_at": _("An empty field has no completion time.")}
                )
            return
        if self.field_type == SignatureFieldType.CHECKBOX:
            if not isinstance(self.value, bool):
                raise ValidationError({"value": _("Checkbox values must be booleans.")})
        elif self.field_type == SignatureFieldType.SIGNATURE:
            legacy_signed = (
                recipient is not None
                and recipient.status in {"signed", "declined"}
                and isinstance(self.value, str)
            )
            if self.has_value and not legacy_signed:
                try:
                    self.value = validate_drawn_signature(self.value)
                except ValidationError as error:
                    raise ValidationError({"value": error.messages}) from error
        elif self.field_type == SignatureFieldType.INITIALS:
            if not isinstance(self.value, (str, dict)):
                raise ValidationError({"value": _("Enter a signature representation.")})
        elif not isinstance(self.value, str):
            raise ValidationError({"value": _("This field requires a text value.")})
        elif self.field_type == SignatureFieldType.DATE and self.value:
            try:
                date.fromisoformat(self.value)
            except ValueError as error:
                raise ValidationError(
                    {"value": _("Enter an ISO calendar date.")}
                ) from error

    def __str__(self) -> str:
        """Identify a request placement without exposing its entered value."""
        return self.key
