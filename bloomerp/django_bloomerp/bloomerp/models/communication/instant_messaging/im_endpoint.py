"""Provider-neutral messaging persistence."""

from django.db import models

from .base import IMModel


class IMEndpoint(IMModel):
    """Represent a business phone number or another sending endpoint on an account."""

    immutable_fields = ("connection_id", "external_id")
    connection = models.ForeignKey(
        "bloomerp.IMConnection", on_delete=models.CASCADE, related_name="endpoints"
    )
    external_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_endpoint"
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "external_id"], name="im_endpoint_external_unique"
            )
        ]

    def __str__(self) -> str:
        """Return the endpoint's human-readable label."""
        return self.name
