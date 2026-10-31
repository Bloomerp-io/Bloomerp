"""Editable document preparation before real signing participants are assigned."""

from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel
from .definition import validate_file_node


class SignaturePreparation(SigningModel):
    """Own draft roles and placements without creating a signing request or recipients."""

    immutable_fields = ("original_file_id",)
    title = models.CharField(_("Title"), max_length=255)
    revision = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    original_file = models.ForeignKey(
        "bloomerp.FileNode",
        on_delete=models.PROTECT,
        related_name="signature_preparations",
        verbose_name=_("Original PDF"),
    )
    source_layout = models.ForeignKey(
        "bloomerp.SignatureLayout",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="preparations",
        verbose_name=_("Source layout"),
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature preparation")
        verbose_name_plural = _("Signature preparations")
        ordering = ("-datetime_created", "pk")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(revision__gte=1),
                name="signature_preparation_revision_positive",
            ),
        ]

    def clean(self) -> None:
        """Require an immutable file node for the document being prepared."""
        super().clean()
        validate_file_node(self.original_file_id, "original_file", self._state.db)

    def __str__(self) -> str:
        """Describe the preparation by its editable title."""
        return self.title
