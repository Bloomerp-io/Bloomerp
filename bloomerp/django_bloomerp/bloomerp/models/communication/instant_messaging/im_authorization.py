"""Provider-neutral messaging persistence."""

import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from bloomerp.communication.utils.crypto import (
    decrypt_email_secret,
    encrypt_email_secret,
    is_encrypted_email_secret,
)

from .base import IMModel


class IMAuthorization(IMModel):
    """Store shared or personal credentials independently from account identity."""

    immutable_fields = ("connection_id", "user_id", "kind")
    connection = models.ForeignKey(
        "bloomerp.IMConnection", on_delete=models.CASCADE, related_name="authorizations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="im_authorizations",
    )
    kind = models.CharField(
        max_length=16,
        choices=[("shared", _("Shared")), ("personal", _("Personal"))],
        default="shared",
    )
    credentials = models.TextField(blank=True, editable=False)
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(IMModel.Meta):
        db_table = "bloomerp_im_authorization"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind="shared", user__isnull=True)
                | models.Q(kind="personal", user__isnull=False),
                name="im_auth_owner_kind",
            ),
            models.UniqueConstraint(
                fields=["connection"],
                condition=models.Q(kind="shared"),
                name="im_auth_one_shared",
            ),
            models.UniqueConstraint(
                fields=["connection", "user"],
                condition=models.Q(kind="personal"),
                name="im_auth_one_personal",
            ),
        ]

    def set_credentials(self, credentials: dict[str, str]) -> None:
        """Encrypt a credential mapping with the existing communications secret key."""
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in credentials.items()
        ):
            raise ValidationError(
                {"credentials": _("Credentials must map strings to strings.")}
            )
        self.credentials = encrypt_email_secret(json.dumps(credentials))

    def get_credentials(self) -> dict[str, str]:
        """Decrypt credentials only for a trusted server-side adapter resolver."""
        return (
            json.loads(decrypt_email_secret(self.credentials))
            if self.credentials
            else {}
        )

    def clean(self) -> None:
        """Reject plaintext or malformed credential storage, including direct assignment."""
        super().clean()
        if self.credentials:
            if not is_encrypted_email_secret(self.credentials):
                raise ValidationError(
                    {"credentials": _("Use set_credentials() to encrypt secrets.")}
                )
            decoded = self.get_credentials()
            if not isinstance(decoded, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in decoded.items()
            ):
                raise ValidationError({"credentials": _("Invalid credential mapping.")})
