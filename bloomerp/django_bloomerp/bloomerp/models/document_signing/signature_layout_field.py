"""Reusable PDF placements assigned to a layout's signer roles."""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .positioned_field import PositionedSignatureField
from .signature_layout_role import SignatureLayoutRole


class SignatureLayoutField(PositionedSignatureField):
    """Describe a field whose definition will be copied into individual requests."""

    immutable_fields = ("layout_id",)
    layout = models.ForeignKey(
        "bloomerp.SignatureLayout",
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name=_("Layout"),
    )
    role = models.ForeignKey(
        "bloomerp.SignatureLayoutRole",
        on_delete=models.RESTRICT,
        related_name="fields",
        verbose_name=_("Role"),
    )

    class Meta(PositionedSignatureField.Meta):
        verbose_name = _("Signature layout field")
        verbose_name_plural = _("Signature layout fields")
        ordering = ("page_number", "y", "x", "key")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            *PositionedSignatureField.Meta.constraints,
            models.UniqueConstraint(
                fields=["layout", "key"], name="signature_layout_field_key_unique"
            ),
        ]

    def clean(self) -> None:
        """Require a placement's role to belong to its own layout."""
        super().clean()
        if (
            self.role_id
            and self.layout_id
            and not SignatureLayoutRole.objects.using(self._state.db)
            .filter(pk=self.role_id, layout_id=self.layout_id)
            .exists()
        ):
            raise ValidationError({"role": _("The role must belong to this layout.")})

    def __str__(self) -> str:
        """Identify a placement by its stable layout-local key."""
        return self.key
