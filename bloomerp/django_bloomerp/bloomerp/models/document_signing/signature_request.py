"""One original PDF and its independent native signing lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.models.definition import (
    BloomerpModelConfig,
    DataviewActionContext,
    FieldSettings,
    ModelViewSettings,
    ObjectHTMLAction,
    ObjectModalAction,
    get_default_dataview_actions,
)
from bloomerp.modules.file_management import FileManagement

from .base import SigningModel
from .definition import sha256_validator, validate_file_node

if TYPE_CHECKING:
    from bloomerp.models import FileNode


def _can_sign_request(request: HttpRequest, signing_request: SignatureRequest) -> bool:
    """Offer signing only for the caller's eligible, authorized recipient assignment."""
    from bloomerp.document_signing.access import get_request_signing_recipient
    from bloomerp.permissions.manager import UserPolicyManager

    return (
        get_request_signing_recipient(UserPolicyManager(request.user), signing_request)
        is not None
    )


def _sign_request_url(signing_request: SignatureRequest) -> str:
    """Open the request's model detail route in the signing modal."""
    return reverse(
        "signature_requests_detail_sign",
        kwargs={"pk": signing_request.pk},
    )


def _can_send_request(request: HttpRequest, signing_request: SignatureRequest) -> bool:
    """Expose delivery only to request managers with unsent email recipients."""
    from bloomerp.document_signing.access import can_send_signing_request
    from bloomerp.permissions.manager import UserPolicyManager

    return can_send_signing_request(signing_request, UserPolicyManager(request.user))


def _send_request_url(signing_request: SignatureRequest) -> str:
    """Open the existing request's invitation composer in a modal."""
    return reverse("signature_requests_detail_send", kwargs={"pk": signing_request.pk})


def _can_assign_request(
    request: HttpRequest, signing_request: SignatureRequest
) -> bool:
    """Expose recipient assignment only for manageable drafts with prepared roles."""
    from bloomerp.document_signing.access import can_assign_signing_request
    from bloomerp.permissions.manager import UserPolicyManager

    return can_assign_signing_request(signing_request, UserPolicyManager(request.user))


def _assign_request_url(signing_request: SignatureRequest) -> str:
    """Open the saved request's role assignment form in the shared modal."""
    return reverse(
        "signature_requests_detail_assign", kwargs={"pk": signing_request.pk}
    )


def _can_copy_links(request: HttpRequest, signing_request: SignatureRequest) -> bool:
    """Restrict bearer signing links to users allowed to distribute this request."""
    from bloomerp.document_signing.access import can_share_signing_request
    from bloomerp.permissions.manager import UserPolicyManager

    return can_share_signing_request(signing_request, UserPolicyManager(request.user))


def _signing_links_context(context: DataviewActionContext) -> dict[str, Any]:
    """Build personal invitation links only for this authorized request's open recipients."""
    from bloomerp.document_signing.access import signing_invitation

    signing_request = context.queryset.first()
    links = []
    if signing_request is not None and _can_copy_links(
        context.request, signing_request
    ):
        for recipient in signing_request.recipients.filter(
            status__in=["pending", "viewed"]
        ):
            links.append(
                {
                    "label": f"{recipient.name} · {recipient.role_label}",
                    "url": context.request.build_absolute_uri(
                        reverse(
                            "signature_requests_detail_invitation",
                            kwargs={
                                "pk": signing_request.pk,
                                "token": signing_invitation(recipient),
                            },
                        )
                    ),
                }
            )
    return {"signing_links": links}


class SignatureRequest(SigningModel):
    """Retain a PDF, recipient snapshots, and its completed output without domain ties."""

    bloomerp_config = BloomerpModelConfig(
        module=FileManagement,
        icon="fa fa-signature",
        description="A request for one or multiple parties to sign a PDF document.",
        field_settings=[
            FieldSettings(
                field="status",
                advanced_rendering=(
                    '<span class="badge badge-sm badge-'
                    '{% if value == "completed" %}success'
                    '{% elif value == "sent" %}info'
                    '{% elif value == "declined" %}danger'
                    '{% elif value == "expired" %}warning'
                    '{% else %}secondary{% endif %}">'
                    "{{ object.get_status_display }}</span>"
                ),
            ),
        ],
        object_actions=[
            ObjectModalAction(
                id="assign",
                label=gettext_noop("Assign"),
                icon="fa-solid fa-user-plus",
                endpoint=_assign_request_url,
                should_render_func=_can_assign_request,
                modal_title=gettext_noop("Assign recipients"),
                modal_size="lg",
            ),
            ObjectModalAction(
                id="send",
                label=gettext_noop("Send"),
                icon="fa-regular fa-paper-plane",
                endpoint=_send_request_url,
                should_render_func=_can_send_request,
                modal_title=gettext_noop("Send signature request"),
                modal_size="xl",
            ),
            ObjectHTMLAction(
                template_name="models/document_signing/copy_links.html",
                context_func=_signing_links_context,
                should_render_func=_can_copy_links,
            ),
            ObjectModalAction(
                id="sign",
                label=gettext_noop("Sign"),
                icon="fa-solid fa-signature",
                endpoint=_sign_request_url,
                should_render_func=_can_sign_request,
                modal_title=gettext_noop("Sign document"),
                modal_size="xl",
            ),
        ],
        model_view_settings=ModelViewSettings(
            dataview_actions=[
                *get_default_dataview_actions(),
            ]
        ),
    )

    class Status(models.TextChoices):
        """Represent the lifecycle of a document sent for native signing."""

        DRAFT = "draft", _("Draft")
        SENT = "sent", _("Sent")
        COMPLETED = "completed", _("Completed")
        DECLINED = "declined", _("Declined")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Expired")

    class SignatureLevel(models.TextChoices):
        """Declare the signature level implemented by the first signing version."""

        SIMPLE = "simple", _("Simple electronic signature")

    title = models.CharField(_("Title"), max_length=255)
    email_account = models.ForeignKey(
        "bloomerp.EmailAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signature_requests",
        verbose_name=_("Sending email account"),
    )
    email_content = models.TextField(_("Invitation message"), blank=True)
    status = models.CharField(
        _("Status"), max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    signature_level = models.CharField(
        _("Signature level"),
        max_length=16,
        choices=SignatureLevel.choices,
        default=SignatureLevel.SIMPLE,
        editable=False,
    )
    source_layout = models.ForeignKey(
        "bloomerp.SignatureLayout",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name=_("Source layout"),
    )
    source_layout_name = models.CharField(
        _("Source layout name"), max_length=255, blank=True
    )
    source_layout_revision = models.PositiveIntegerField(
        _("Source layout revision"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    source_preparation = models.ForeignKey(
        "bloomerp.SignaturePreparation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name=_("Source preparation"),
    )
    source_preparation_revision = models.PositiveIntegerField(
        _("Source preparation revision"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    original_file: FileNode = models.ForeignKey(
        "bloomerp.FileNode",
        on_delete=models.PROTECT,
        related_name="original_signature_requests",
        verbose_name=_("Original PDF"),
    )
    original_sha256 = models.CharField(
        _("Original SHA-256"), max_length=64, blank=True, validators=[sha256_validator]
    )
    signed_file = models.ForeignKey(
        "bloomerp.FileNode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="completed_signature_requests",
        verbose_name=_("Signed PDF"),
    )
    signed_sha256 = models.CharField(
        _("Signed SHA-256"), max_length=64, blank=True, validators=[sha256_validator]
    )
    sent_at = models.DateTimeField(_("Sent at"), null=True, blank=True)
    expires_at = models.DateTimeField(_("Expires at"), null=True, blank=True)
    completed_at = models.DateTimeField(_("Completed at"), null=True, blank=True)

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature request")
        verbose_name_plural = _("Signature requests")
        ordering = ("-datetime_created", "pk")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(signature_level="simple"),
                name="signature_request_native_level",
            ),
            models.CheckConstraint(
                condition=models.Q(signed_file__isnull=True)
                | ~models.Q(signed_file=models.F("original_file")),
                name="signature_request_separate_output",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="completed",
                        completed_at__isnull=False,
                        signed_file__isnull=False,
                    )
                    & ~models.Q(signed_sha256="")
                )
                | models.Q(
                    completed_at__isnull=True,
                    signed_file__isnull=True,
                    signed_sha256="",
                )
                & ~models.Q(status="completed"),
                name="signature_request_completion_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "cancelled"])
                | models.Q(sent_at__isnull=False) & ~models.Q(original_sha256=""),
                name="signature_request_dispatch_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(sent_at__isnull=True)
                | ~models.Q(original_sha256=""),
                name="signature_request_sent_has_digest",
            ),
            models.CheckConstraint(
                condition=models.Q(completed_at__isnull=True)
                | models.Q(completed_at__gte=models.F("sent_at")),
                name="signature_request_completion_time_order",
            ),
        ]

    def validate_previous(self, previous: SigningModel) -> None:
        """Freeze dispatched content and prevent reopening a terminal request."""
        super().validate_previous(previous)
        transitions = {
            self.Status.DRAFT: {
                self.Status.DRAFT,
                self.Status.SENT,
                self.Status.CANCELLED,
            },
            self.Status.SENT: set(self.Status.values) - {self.Status.DRAFT},
        }
        if self.status not in transitions.get(previous.status, {previous.status}):
            raise ValidationError(
                {"status": _("This request transition is not allowed.")}
            )
        if previous.status != self.Status.DRAFT:
            self.require_unchanged(
                previous,
                (
                    "title",
                    "source_layout_id",
                    "source_layout_name",
                    "source_layout_revision",
                    "source_preparation_id",
                    "source_preparation_revision",
                    "original_file_id",
                    "original_sha256",
                    "signature_level",
                    "sent_at",
                    "expires_at",
                    "email_account_id",
                    "email_content",
                ),
            )
        if previous.status == self.Status.COMPLETED:
            self.require_unchanged(
                previous, ("signed_file_id", "signed_sha256", "completed_at")
            )

    def clean(self) -> None:
        """Require coherent dispatch, provenance, recipients, and completion evidence."""
        super().clean()
        if self.signature_level != self.SignatureLevel.SIMPLE:
            raise ValidationError(
                {"signature_level": _("Only simple electronic signing is implemented.")}
            )
        validate_file_node(self.original_file_id, "original_file", self._state.db)
        validate_file_node(self.signed_file_id, "signed_file", self._state.db)
        exists = type(self).objects.using(self._state.db).filter(pk=self.pk).exists()
        if not exists and self.status != self.Status.DRAFT:
            raise ValidationError({"status": _("Create signing requests as drafts.")})
        if self.status == self.Status.DRAFT and self.sent_at is not None:
            raise ValidationError({"sent_at": _("A draft has not been dispatched.")})
        if self.source_layout_id and (
            not self.source_layout_name or not self.source_layout_revision
        ):
            raise ValidationError(
                {"source_layout": _("Snapshot the layout name and revision.")}
            )
        if bool(self.source_preparation_id) != bool(self.source_preparation_revision):
            raise ValidationError(
                {
                    "source_preparation": _(
                        "Retain the preparation and its revision together."
                    )
                }
            )
        if self.sent_at and self.expires_at and self.expires_at <= self.sent_at:
            raise ValidationError({"expires_at": _("Expiry must follow dispatch.")})
        if self.status == self.Status.SENT:
            if not self.recipients.exists():
                raise ValidationError(
                    {"status": _("A signing request needs recipients.")}
                )
            if self.recipients.filter(fields__isnull=True).exists():
                raise ValidationError(
                    {"status": _("Each recipient needs at least one field.")}
                )
        if self.status == self.Status.COMPLETED and (
            not self.recipients.exists()
            or self.recipients.exclude(status="signed").exists()
        ):
            raise ValidationError(
                {"status": _("Every recipient must sign before completion.")}
            )

    def validate_deletion(self) -> None:
        """Allow draft cleanup while retaining dispatched requests and their files."""
        super().validate_deletion()
        if self.status != self.Status.DRAFT:
            raise ValidationError("Only draft signing requests can be deleted.")

    @property
    def number_of_parties(self) -> int:
        """Return the number of recipients assigned to this signing request."""
        return self.recipients.count()

    def get_absolute_url(self) -> str:
        """Open the request's creation and signer-progress timeline."""
        return reverse("signature_requests_detail_view_status", kwargs={"pk": self.pk})

    def __str__(self) -> str:
        """Describe a request independently of the originating business record."""
        return self.title
