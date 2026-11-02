"""Draft field placements owned by a generic preparation role."""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .positioned_field import PositionedSignatureField
from .signature_preparation_role import SignaturePreparationRole


class SignaturePreparationField(PositionedSignatureField):
    """Store a role-based placement before a request assigns a concrete recipient."""

    immutable_fields = ("preparation_id", "key")
    preparation = models.ForeignKey(
        "bloomerp.SignaturePreparation", on_delete=models.CASCADE, related_name="fields"
    )
    role = models.ForeignKey(
        "bloomerp.SignaturePreparationRole",
        on_delete=models.RESTRICT,
        related_name="fields",
    )

    class Meta(PositionedSignatureField.Meta):
        verbose_name = _("Signature preparation field")
        verbose_name_plural = _("Signature preparation fields")
        ordering = ("page_number", "y", "x", "key")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            *PositionedSignatureField.Meta.constraints,
            models.UniqueConstraint(
                fields=["preparation", "key"], name="signature_prep_field_key_unique"
            ),
        ]

    def clean(self) -> None:
        """Keep every field's role inside its own document preparation."""
        super().clean()
        if (
            self.role_id
            and self.preparation_id
            and not SignaturePreparationRole.objects.using(self._state.db)
            .filter(pk=self.role_id, preparation_id=self.preparation_id)
            .exists()
        ):
            raise ValidationError(
                {"role": _("The role must belong to this preparation.")}
            )

    def __str__(self) -> str:
        """Identify the placement by its stable preparation-local key."""
        return self.key
