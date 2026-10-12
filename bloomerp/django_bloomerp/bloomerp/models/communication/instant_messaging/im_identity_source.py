"""Associate stable identities with mutable source phone fields."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from .base import IMModel


class IMIdentitySource(IMModel):
    """Retain record and field provenance without making it the recipient identity."""

    identity = models.ForeignKey(
        "bloomerp.IMIdentity",
        verbose_name=_("Identity"),
        on_delete=models.CASCADE,
        related_name="sources",
    )
    content_type = models.ForeignKey(
        "contenttypes.ContentType",
        verbose_name=_("Content type"),
        on_delete=models.CASCADE,
    )
    object_id = models.CharField(_("Object identifier"), max_length=255)
    field_name = models.CharField(_("Phone field"), max_length=255)

    class Meta(IMModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["identity", "content_type", "object_id", "field_name"],
                name="im_identity_source_unique",
            )
        ]

    def __str__(self) -> str:
        """Return source provenance without reading the linked object's fields."""
        return f"{self.content_type_id}:{self.object_id}:{self.field_name}"
