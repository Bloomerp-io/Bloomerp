"""Reusable signing layouts that can be applied to any PDF source."""

from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import SigningModel
from .definition import validate_file_node


class SignatureLayout(SigningModel):
    """Group reusable field placements and signer roles independently of templates."""

    immutable_fields = ("document_template_id", "revision")
    document_template = models.ForeignKey(
        "bloomerp.DocumentTemplate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signature_layout_revisions",
        verbose_name=_("Document template"),
    )
    name = models.CharField(_("Name"), max_length=255)
    revision = models.PositiveIntegerField(
        _("Revision"), default=1, validators=[MinValueValidator(1)]
    )
    preview_file = models.ForeignKey(
        "bloomerp.FileNode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signature_layout_previews",
        verbose_name=_("Preview PDF"),
    )

    class Meta(SigningModel.Meta):
        verbose_name = _("Signature layout")
        verbose_name_plural = _("Signature layouts")
        ordering = ("name", "pk")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(revision__gte=1),
                name="signature_layout_revision_positive",
            ),
            models.UniqueConstraint(
                fields=("document_template", "revision"),
                name="signature_layout_template_revision_unique",
            ),
        ]

    def clean(self) -> None:
        """Ensure an optional preview refers to file content."""
        super().clean()
        validate_file_node(self.preview_file_id, "preview_file", self._state.db)

    def __str__(self) -> str:
        """Describe the reusable layout by its user-assigned name."""
        return self.name
