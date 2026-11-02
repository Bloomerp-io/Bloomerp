"""Account-independent configuration of external MCP integrations."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop

from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ApiSettings,
    BloomerpModelConfig,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)
from bloomerp.modules.bloomai import BloomAIModule

from .base import AgentQuerySet, agent_search_settings


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
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("MCP integrations"),
                    display_fields=[
                        "name",
                        "enabled",
                        "connection_mode",
                        "authentication_type",
                    ],
                    sort_field="name",
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Server"),
                            items=[
                                LayoutItem(id="name"),
                                LayoutItem(id="enabled"),
                                LayoutItem(id="endpoint_url", colspan=2),
                            ],
                        ),
                        LayoutRow(
                            columns=2,
                            title=gettext_noop("Authentication"),
                            items=[
                                LayoutItem(id="connection_mode"),
                                LayoutItem(id="authentication_type"),
                                LayoutItem(id="oauth_client_id", colspan=2),
                                LayoutItem(id="oauth_scopes", colspan=2),
                            ],
                        ),
                    ]
                )
            ]
        ),
        module=BloomAIModule,
        api_settings=ApiSettings(enable_auto_generation=False),
        string_search_settings=agent_search_settings(allow_global_search=True),
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
