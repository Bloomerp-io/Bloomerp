"""Provider-neutral messaging persistence."""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMIdentity(IMModel):
    """Keep provider identities without requiring a CRM contact record."""

    immutable_fields = ("connection_id", "external_id")
    connection = models.ForeignKey(
        "bloomerp.IMConnection", on_delete=models.CASCADE, related_name="identities"
    )
    external_id = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True)
    address = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=2048, blank=True)
    content_type = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    object_id = models.CharField(max_length=255, null=True, blank=True)
    related_object = GenericForeignKey("content_type", "object_id")

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_identity"
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"], name="im_identity_external_unique"
            )
        ]
        indexes = [
            models.Index(
                fields=["content_type", "object_id"], name="im_identity_record_idx"
            )
        ]

    def clean(self) -> None:
        """Require both halves of an optional CRM link without merging identities."""
        super().clean()
        if bool(self.content_type_id) != bool(self.object_id):
            raise ValidationError(
                {"object_id": _("Provide both a content type and an object ID.")}
            )

    def __str__(self) -> str:
        """Return a provider-resolved label with a stable identity fallback."""
        return self.display_name or self.address or self.external_id
