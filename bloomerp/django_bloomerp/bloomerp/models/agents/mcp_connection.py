"""Private, encrypted account credentials for external MCP integrations."""

from __future__ import annotations

import base64
import json
from typing import Any, ClassVar

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic import ValidationError as SchemaValidationError

from .ai_agent import EncryptedCredentialsEnvelope
from .base import AgentModel
from .mcp_server import MCPIntegration


class APIKeyCredentials(BaseModel):
    """Validate an API key while masking secrets in string and JSON output."""

    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


class OAuthCredentials(BaseModel):
    """Store OAuth tokens without exposing them through ordinary serialization."""

    model_config = ConfigDict(extra="forbid")
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    issuer: str | None = None


class MCPConnection(AgentModel):
    """Associate private credentials with a shared integration or one user."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        READY = "ready", _("Ready")
        EXPIRED = "expired", _("Expired")
        ERROR = "error", _("Error")
        REVOKED = "revoked", _("Revoked")

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_mcp_connection"
        verbose_name = _("MCP Connection")
        verbose_name_plural = _("MCP Connections")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["integration"],
                condition=models.Q(user__isnull=True),
                name="mcp_connection_unique_shared",
            ),
            models.UniqueConstraint(
                fields=["integration", "user"],
                condition=models.Q(user__isnull=False),
                name="mcp_connection_unique_personal",
            ),
        ]

    immutable_fields = ("integration_id", "user_id")
    integration = models.ForeignKey(
        MCPIntegration, on_delete=models.CASCADE, related_name="connections"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="mcp_connections",
    )
    credentials_encrypted = models.JSONField(default=dict, blank=True, editable=False)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    last_checked_at = models.DateTimeField(null=True, blank=True, editable=False)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        """Display connection identity and status without account or secret values."""
        return f"MCP connection {self.pk} ({self.status})"

    def _cipher(self) -> Fernet:
        """Derive a purpose-specific Fernet key using the AIAgent key convention."""
        digest = salted_hmac(
            "bloomerp.mcp.credentials",
            "v1",
            secret=settings.SECRET_KEY,
            algorithm="sha256",
        ).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _validate_credentials(
        self, values: dict[str, Any]
    ) -> APIKeyCredentials | OAuthCredentials:
        """Validate the selected authentication schema without echoing secret inputs."""
        try:
            authentication = self.integration.authentication_type
            if authentication == MCPIntegration.AuthenticationType.API_KEY:
                credentials = APIKeyCredentials.model_validate(values)
                required = credentials.api_key
            elif authentication == MCPIntegration.AuthenticationType.OAUTH:
                credentials = OAuthCredentials.model_validate(values)
                required = credentials.access_token
            else:
                raise ValueError("No credentials allowed")
            if not required.get_secret_value().strip():
                raise ValueError("Empty credential")
            return credentials
        except (ValueError, TypeError, SchemaValidationError):
            raise ValidationError(_("Invalid MCP credentials.")) from None

    def set_credentials(self, values: dict[str, Any]) -> None:
        """Validate plaintext inputs and assign only their encrypted envelope."""
        self._validate_credentials(values)
        try:
            ciphertext = (
                self._cipher()
                .encrypt(json.dumps(values, allow_nan=False).encode())
                .decode()
            )
        except (ValueError, TypeError):
            raise ValidationError(_("Invalid MCP credentials.")) from None
        self.credentials_encrypted = EncryptedCredentialsEnvelope(
            ciphertext=ciphertext
        ).model_dump(mode="json")

    def validated_credentials(self) -> APIKeyCredentials | OAuthCredentials:
        """Decrypt stored credentials explicitly and return a masked schema object."""
        try:
            envelope = EncryptedCredentialsEnvelope.model_validate(
                self.credentials_encrypted
            )
            values = json.loads(self._cipher().decrypt(envelope.ciphertext.encode()))
        except (SchemaValidationError, InvalidToken, ValueError, TypeError):
            raise ValidationError(
                _("MCP credentials could not be decrypted.")
            ) from None
        return self._validate_credentials(values)

    def clean(self) -> None:
        """Enforce connection ownership, authentication and valid encrypted storage."""
        super().clean()
        if not self.integration_id:
            return
        integration = self.integration
        if integration.authentication_type == MCPIntegration.AuthenticationType.NONE:
            raise ValidationError(
                {"integration": _("No-auth integrations do not need connections.")}
            )
        personal = integration.connection_mode == MCPIntegration.ConnectionMode.PERSONAL
        if personal != (self.user_id is not None):
            raise ValidationError(
                {
                    "user": _(
                        "Personal connections require a user; shared connections must have no user."
                    )
                }
            )
        if self.credentials_encrypted:
            self.validated_credentials()
        elif self.status == self.Status.READY:
            raise ValidationError(
                {"status": _("Ready connections require credentials.")}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate against the locked, current integration instead of cached settings."""
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            if self.integration_id:
                self.integration = (
                    MCPIntegration.objects.using(database)
                    .select_for_update()
                    .get(pk=self.integration_id)
                )
            super().save(*args, **kwargs)
