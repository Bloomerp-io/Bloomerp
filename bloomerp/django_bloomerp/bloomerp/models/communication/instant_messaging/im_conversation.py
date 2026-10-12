"""Provider-neutral messaging persistence."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .base import IMModel


class IMConversation(IMModel):
    """Own an independent direct, group or channel conversation on one connection."""

    immutable_fields = ("connection_id", "endpoint_id", "kind")
    connection = models.ForeignKey(
        "bloomerp.IMConnection",
        on_delete=models.PROTECT,
        related_name="conversations",
        null=True,
        blank=True,
    )
    endpoint = models.ForeignKey(
        "bloomerp.IMEndpoint",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="conversations",
    )
    kind = models.CharField(
        max_length=16,
        choices=[
            ("direct", _("Direct")),
            ("group", _("Group")),
            ("channel", _("Channel")),
        ],
        default="direct",
    )
    name = models.CharField(max_length=255, blank=True)
    provider_thread_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("open", _("Open")),
            ("resolved", _("Resolved")),
            ("archived", _("Archived")),
        ],
        default="open",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_im_conversations",
    )
    assigned_team = models.ForeignKey(
        "auth.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="im_conversations",
    )
    needs_reply = models.BooleanField(default=False)
    last_activity_at = models.DateTimeField(default=timezone.now)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_conversation"
        ordering = ["-last_activity_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "endpoint", "provider_thread_id"],
                condition=~models.Q(provider_thread_id="")
                & models.Q(endpoint__isnull=False),
                name="im_conv_endpoint_thread",
            ),
            models.UniqueConstraint(
                fields=["connection", "provider_thread_id"],
                condition=~models.Q(provider_thread_id="")
                & models.Q(endpoint__isnull=True),
                name="im_conv_account_thread",
            ),
        ]

    def clean(self) -> None:
        """Reject endpoints belonging to a different provider account."""
        super().clean()
        if self.connection_id is None and (self.endpoint_id or self.provider_thread_id):
            raise ValidationError(
                "Internal conversations cannot have external endpoints or thread IDs."
            )
        if self.endpoint_id and self.endpoint.connection_id != self.connection_id:
            raise ValidationError(
                {"endpoint": _("The endpoint must belong to this connection.")}
            )

    def __str__(self) -> str:
        """Return a label without exposing message content."""
        return self.name or str(self.pk)
