"""Named signer placeholders belonging to a reusable signing layout."""

from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel


class SignatureLayoutRole(SigningModel):
    """Define a domain-neutral role that requests later assign to a real person."""

    immutable_fields = ("layout_id",)
    layout = models.ForeignKey(
        "bloomerp.SignatureLayout",
        on_delete=models.CASCADE,
        related_name="roles",
        verbose_name=_("Layout"),
    )
    key = models.SlugField(_("Key"), max_length=100)
    label = models.CharField(_("Label"), max_length=255)
    default_signing_order = models.PositiveIntegerField(
        _("Default signing order"), default=1, validators=[MinValueValidator(1)]
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature layout role")
        verbose_name_plural = _("Signature layout roles")
        ordering = ("default_signing_order", "key")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["layout", "key"], name="signature_role_layout_key_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(default_signing_order__gte=1),
                name="signature_role_order_positive",
            ),
        ]

    def __str__(self) -> str:
        """Return the configurable label without resolving a business object."""
        return self.label
