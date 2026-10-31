"""Immutable file-backed evidence retained with document signing requests."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel
from .definition import sha256_validator, validate_file_node
from .signature_recipient import SignatureRecipient


class SignatureArtifact(SigningModel):
    """Retain completion certificates, audit reports, and other signing evidence."""

    class Kind(models.TextChoices):
        """Classify evidence without coupling it to a particular signing provider."""

        COMPLETION_CERTIFICATE = "completion_certificate", _("Completion certificate")
        AUDIT_REPORT = "audit_report", _("Audit report")
        CONSENT_RECORD = "consent_record", _("Consent record")
        OTHER = "other", _("Other")

    request_bound = True
    append_only = True
    request = models.ForeignKey(
        "bloomerp.SignatureRequest",
        on_delete=models.PROTECT,
        related_name="artifacts",
        verbose_name=_("Request"),
    )
    recipient = models.ForeignKey(
        "bloomerp.SignatureRecipient",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="artifacts",
        verbose_name=_("Recipient"),
    )
    file = models.ForeignKey(
        "bloomerp.FileNode",
        on_delete=models.PROTECT,
        related_name="signature_artifacts",
        verbose_name=_("Evidence file"),
    )
    kind = models.CharField(_("Kind"), max_length=24, choices=Kind.choices)
    sha256 = models.CharField(
        _("SHA-256"), max_length=64, validators=[sha256_validator]
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature artifact")
        verbose_name_plural = _("Signature artifacts")
        ordering = ("datetime_created", "pk")

    def clean(self) -> None:
        """Require file content and same-request ownership for recipient evidence."""
        super().clean()
        validate_file_node(self.file_id, "file", self._state.db)
        if (
            self.recipient_id
            and not SignatureRecipient.objects.using(self._state.db)
            .filter(pk=self.recipient_id, request_id=self.request_id)
            .exists()
        ):
            raise ValidationError(
                {"recipient": _("The recipient must belong to this request.")}
            )

    def __str__(self) -> str:
        """Identify evidence by its kind and request without resolving a business object."""
        return f"{self.kind}: {self.request_id}"
