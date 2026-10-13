"""Account-independent configuration of external MCP integrations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig
from bloomerp.modules.bloomai import BloomAIModule

from .base import AgentQuerySet


class MCPIntegration(BloomerpModel):
    """Describe an external server independently of its account credentials."""

    class ConnectionMode(models.TextChoices):
        SHARED = "shared", _("Shared")
        PERSONAL = "personal", _("Personal")

    class AuthenticationType(models.TextChoices):
        NONE = "none", _("None")
        API_KEY = "api_key", _("API key")
        OAUTH = "oauth", _("OAuth")

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_mcp_integration"
        verbose_name = _("MCP Integration")
        verbose_name_plural = _("MCP Integrations")

    bloomerp_config = BloomerpModelConfig(
        module=BloomAIModule,
        api_settings=ApiSettings(enable_auto_generation=False),
        description="External MCP server configuration independent of an account.",
    )
    objects = AgentQuerySet.as_manager()
    avatar = None
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    endpoint_url = models.URLField(max_length=2048, verbose_name=_("Endpoint URL"))
    enabled = models.BooleanField(default=True, verbose_name=_("Enabled"))
    connection_mode = models.CharField(
        max_length=10, choices=ConnectionMode.choices, default=ConnectionMode.SHARED
    )
    authentication_type = models.CharField(
        max_length=10,
        choices=AuthenticationType.choices,
        default=AuthenticationType.NONE,
    )
    oauth_client_id = models.CharField(
        max_length=2048,
        blank=True,
        default="",
        help_text=_(
            "Optional pre-registered OAuth client ID. Leave blank for automatic client registration."
        ),
    )
    oauth_scopes = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        help_text=_(
            "Optional space-separated OAuth scopes; a server challenge takes precedence."
        ),
    )

    def __str__(self) -> str:
        """Display only the integration's human-readable name."""
        return self.name

    def clean(self) -> None:
        """Reject secret-bearing URLs and changes that invalidate connections."""
        super().clean()
        try:
            endpoint = urlsplit(self.endpoint_url)
            valid_endpoint = (
                endpoint.scheme in {"http", "https"}
                and endpoint.hostname
                and endpoint.username is None
                and endpoint.password is None
                and not endpoint.query
                and not endpoint.fragment
            )
        except ValueError:
            valid_endpoint = False
        if not valid_endpoint:
            raise ValidationError(
                {
                    "endpoint_url": _(
                        "Use an HTTP(S) endpoint without credentials, query parameters, or fragments."
                    )
                }
            )
        database = self._state.db or router.db_for_write(type(self), instance=self)
        old = type(self).objects.using(database).filter(pk=self.pk).first()
        if old is not None and old.connections.using(database).exists():
            errors = {
                field: _("Remove existing connections before changing this setting.")
                for field in (
                    "connection_mode",
                    "authentication_type",
                    "endpoint_url",
                    "oauth_client_id",
                    "oauth_scopes",
                )
                if getattr(old, field) != getattr(self, field)
            }
            if errors:
                raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Serialize configuration changes against validated connection writes."""
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            type(self).objects.using(database).select_for_update().filter(
                pk=self.pk
            ).first()
            self.full_clean()
            super().save(*args, **kwargs)
