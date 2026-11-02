"""Actual signer identities copied into a document signing request."""

from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel, signing_builder_config
from .definition import validate_json_object


class SignatureRecipient(SigningModel):
    """Assign one request role to an email recipient without requiring a user account."""

    bloomerp_config = signing_builder_config()

    class Status(models.TextChoices):
        """Describe one recipient's progress through native signing."""

        PENDING = "pending", _("Pending")
        VIEWED = "viewed", _("Viewed")
        SIGNED = "signed", _("Signed")
        DECLINED = "declined", _("Declined")

    request_bound = True
    immutable_fields = ("request_id",)
    request = models.ForeignKey(
        "bloomerp.SignatureRequest",
        on_delete=models.CASCADE,
        related_name="recipients",
        verbose_name=_("Request"),
    )
    role_key = models.SlugField(_("Role key"), max_length=100)
    role_label = models.CharField(_("Role label"), max_length=255)
    name = models.CharField(_("Name"), max_length=255)
    email = models.EmailField(_("Email"), blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signature_recipients",
        verbose_name=_("User"),
    )
    signing_order = models.PositiveIntegerField(
        _("Signing order"), default=1, validators=[MinValueValidator(1)]
    )
    status = models.CharField(
        _("Status"), max_length=16, choices=Status.choices, default=Status.PENDING
    )
    consent_text = models.TextField(_("Accepted consent text"), blank=True)
    consented_at = models.DateTimeField(_("Consented at"), null=True, blank=True)
    signed_at = models.DateTimeField(_("Signed at"), null=True, blank=True)
    declined_at = models.DateTimeField(_("Declined at"), null=True, blank=True)
    decline_reason = models.TextField(_("Decline reason"), blank=True)
    email_delivery = models.JSONField(
        _("Email delivery"),
        default=dict,
        blank=True,
        editable=False,
        validators=[validate_json_object],
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature recipient")
        verbose_name_plural = _("Signature recipients")
        ordering = ("signing_order", "role_key")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["request", "role_key"], name="signature_recipient_role_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(signing_order__gte=1),
                name="signature_recipient_order_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="signed",
                        signed_at__isnull=False,
                        consented_at__isnull=False,
                    )
                    & ~models.Q(consent_text="")
                )
                | (~models.Q(status="signed") & models.Q(signed_at__isnull=True)),
                name="signature_recipient_signed_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(status="declined", declined_at__isnull=False)
                | (~models.Q(status="declined") & models.Q(declined_at__isnull=True)),
                name="signature_recipient_declined_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(signed_at__isnull=True)
                | models.Q(signed_at__gte=models.F("consented_at")),
                name="signature_recipient_consent_time_order",
            ),
        ]

    def validate_previous(self, previous: SigningModel) -> None:
        """Freeze dispatched identities and retain final responses and consent."""
        super().validate_previous(previous)
        request = self.get_request()
        if request is not None and request.status != "draft":
            self.require_unchanged(
                previous,
                (
                    "role_key",
                    "role_label",
                    "name",
                    "email",
                    "user_id",
                    "signing_order",
                ),
            )
        if previous.status in {self.Status.SIGNED, self.Status.DECLINED}:
            self.require_unchanged(
                previous,
                (
                    "status",
                    "consent_text",
                    "consented_at",
                    "signed_at",
                    "declined_at",
                    "decline_reason",
                ),
            )
        if previous.consented_at is not None:
            self.require_unchanged(previous, ("consent_text", "consented_at"))
        if previous.status == self.Status.VIEWED and self.status == self.Status.PENDING:
            raise ValidationError(
                {"status": _("A viewed request cannot become unseen.")}
            )
        if request is not None and request.status not in {"draft", "sent"}:
            self.require_unchanged(
                previous,
                (
                    "status",
                    "consent_text",
                    "consented_at",
                    "signed_at",
                    "declined_at",
                    "decline_reason",
                ),
            )

    def clean(self) -> None:
        """Validate responses against the current request and retained consent."""
        super().clean()
        if not self.user_id and not self.email:
            raise ValidationError(
                {"email": _("Choose an internal user or an email address.")}
            )
        request = self.get_request()
        if request is None:
            return
        exists = type(self).objects.using(self._state.db).filter(pk=self.pk).exists()
        if not exists and request.status != "draft":
            raise ValidationError(
                {"request": _("Add recipients while the request is a draft.")}
            )
        if request.status == "draft" and (
            self.status != self.Status.PENDING or self.consented_at is not None
        ):
            raise ValidationError(
                {"status": _("A draft recipient cannot have responded.")}
            )
        if bool(self.consent_text) != (self.consented_at is not None):
            raise ValidationError(
                {"consent_text": _("Retain consent text and its time together.")}
            )
        if (
            self.consented_at
            and request.sent_at
            and self.consented_at < request.sent_at
        ):
            raise ValidationError({"consented_at": _("Consent must follow dispatch.")})
        if self.declined_at and request.sent_at and self.declined_at < request.sent_at:
            raise ValidationError({"declined_at": _("Declining must follow dispatch.")})
        if self.status == self.Status.SIGNED:
            if any(not field.has_value for field in self.fields.filter(required=True)):
                raise ValidationError(
                    {"status": _("Complete every required field before signing.")}
                )
            if (
                request.recipients.filter(signing_order__lt=self.signing_order)
                .exclude(status=self.Status.SIGNED)
                .exists()
            ):
                raise ValidationError(
                    {"status": _("Earlier recipients must sign first.")}
                )

    def __str__(self) -> str:
        """Describe the recipient using their retained name and email."""
        return f"{self.name} <{self.email}>"
