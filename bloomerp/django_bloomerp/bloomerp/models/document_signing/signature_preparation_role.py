"""Generic signer roles belonging to one document preparation."""

from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel


class SignaturePreparationRole(SigningModel):
    """Store a role such as Director without knowing the eventual person's identity."""

    immutable_fields = ("preparation_id", "key")
    preparation = models.ForeignKey(
        "bloomerp.SignaturePreparation", on_delete=models.CASCADE, related_name="roles"
    )
    key = models.SlugField(_("Key"), max_length=100)
    label = models.CharField(_("Role name"), max_length=255)
    signing_order = models.PositiveIntegerField(
        _("Signing order"), default=1, validators=[MinValueValidator(1)]
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature preparation role")
        verbose_name_plural = _("Signature preparation roles")
        ordering = ("signing_order", "datetime_created", "pk")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["preparation", "key"], name="signature_prep_role_key_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(signing_order__gte=1),
                name="signature_prep_role_order_positive",
            ),
        ]

    def __str__(self) -> str:
        """Return the configurable role label."""
        return self.label
