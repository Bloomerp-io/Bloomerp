"""Provider-neutral messaging persistence."""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMIdentity(IMModel):
    """Keep provider identities without requiring a CRM contact record."""

    immutable_fields = ("connection_id", "external_id", "provider_key")
    provider_key = models.CharField(
        _("Provider"), max_length=32, default="", blank=True
    )
    connection = models.ForeignKey(
        "bloomerp.IMConnection",
        on_delete=models.CASCADE,
        related_name="identities",
        null=True,
        blank=True,
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
                fields=["provider_key", "external_id"],
                condition=models.Q(connection__isnull=True),
                name="im_local_identity_unique",
            ),
            models.UniqueConstraint(
                fields=["connection", "external_id"], name="im_identity_external_unique"
            ),
        ]
        indexes = [
            models.Index(
                fields=["content_type", "object_id"], name="im_identity_record_idx"
            )
        ]

    def clean(self) -> None:
        """Require both halves of an optional CRM link without merging identities."""
        super().clean()
        if self.connection_id and not self.provider_key:
            self.provider_key = self.connection.provider
        if self.provider_key == "phone" and (
            self.connection_id or self.address != self.external_id
        ):
            raise ValidationError(
                _(
                    "Phone identities require their original address and no IM connection."
                )
            )
        if not self.connection_id and self.provider_key != "phone":
            raise ValidationError(
                _("A configured connection is required for this identity.")
            )
        if bool(self.content_type_id) != bool(self.object_id):
            raise ValidationError(
                {"object_id": _("Provide both a content type and an object ID.")}
            )

    def __str__(self) -> str:
        """Return a provider-resolved label with a stable identity fallback."""
        return self.display_name or self.address or self.external_id
