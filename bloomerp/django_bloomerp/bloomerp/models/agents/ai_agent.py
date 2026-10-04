"""Shared model configuration with encrypted, non-public execution credentials."""

from __future__ import annotations

import base64
import json
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as SchemaValidationError

from bloomerp.agents.definition import RunBudgets
from bloomerp.agents.providers.definition import AIProviderCredentialsSchema
from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY, provider_choices
from bloomerp.agents.runtime import AgentRuntimeConfig, AgentRuntimeCredentials
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
    DetailTab,
    DetailTabsConfiguration,
    DetailViewSettings,
    FieldLayout,
    LayoutItem,
    LayoutRow,
    StringSearchSettings,
)
from bloomerp.modules.bloomai import BloomAIModule


class EncryptedCredentialsEnvelope(BaseModel):
    """Describe versioned encryption metadata without serializing decrypted credentials."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    algorithm: Literal["fernet"] = "fernet"
    ciphertext: str = Field(min_length=1)


class AIAgent(BloomerpModel):
    """Configure an assistant with explicit user/group grants and encrypted credentials."""

    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_ai_agent"
        verbose_name = _("AI Agent")
        verbose_name_plural = _("AI Agents")

    # Plaintext credentials stay out of generated APIs, generic forms, and activity logs.
    bloomerp_config = BloomerpModelConfig(
        module=BloomAIModule,
        detail_view_settings=DetailViewSettings(
            layouts=[
                FieldLayout(
                    rows=[
                        LayoutRow(
                            columns=2,
                            items=[
                                LayoutItem(id="name", colspan=1),
                                LayoutItem(id="enabled", colspan=1),
                                LayoutItem(
                                    id="access",
                                    colspan=2,
                                    config={
                                        "inline_fields": ["name", "users", "groups"]
                                    },
                                ),
                            ],
                        ),
                        LayoutRow(
                            columns=3,
                            title="Tools",
                            items=[
                                LayoutItem(id="internal_tool_mode", colspan=1),
                                LayoutItem(id="internal_tools", colspan=2),
                                LayoutItem(id="internal_resource_mode", colspan=1),
                                LayoutItem(id="internal_resources", colspan=2),
                                LayoutItem(id="mcp_integrations", colspan=3),
                            ],
                        ),
                    ]
                )
            ],
            tab_configurations=[
                DetailTabsConfiguration(
                    tabs=[
                        DetailTab(name="Details", url_name="ai_agents_detail_overview"),
                        DetailTab(
                            name="Reconfigure", url_name="ai_agents_detail_reconfigure"
                        ),
                        DetailTab(name="Delete", url_name="ai_agents_detail_delete"),
                        DetailTab(
                            name="Access",
                            url_name="ai_agents_detail_access_relationship",
                        ),
                    ]
                )
            ],
        ),
        api_settings=ApiSettings(enable_auto_generation=False),
        activity_log_settings=ActivityLogSettings(enabled=True),
        string_search_settings=StringSearchSettings(allow_global_search=True),
    )

    avatar = None

    class InternalToolMode(models.TextChoices):
        ALL = "all", _("All built-in Bloomerp tools")
        SELECTED = "selected", _("Selected built-in Bloomerp tools only")

    internal_tool_mode = models.CharField(
        max_length=10,
        choices=InternalToolMode.choices,
        default=InternalToolMode.ALL,
        verbose_name=_("Built-in Bloomerp tool access"),
        help_text=_(
            "All includes newly registered tools. Selected with no tools allows none. User permissions still apply."
        ),
    )
    internal_tools = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Selected built-in Bloomerp tools"),
        help_text=_(
            "Stable MCP tool names. Unavailable tools cannot run. Used only when access is set to selected tools."
        ),
    )

    class InternalResourceMode(models.TextChoices):
        ALL = "all", _("All built-in Bloomerp resources")
        SELECTED = "selected", _("Selected built-in Bloomerp resources only")

    internal_resource_mode = models.CharField(
        max_length=10,
        choices=InternalResourceMode.choices,
        default=InternalResourceMode.ALL,
        verbose_name=_("Built-in Bloomerp resource access"),
        help_text=_(
            "All includes newly registered resources. Selected with no resources allows none. User permissions still apply."
        ),
    )
    internal_resources = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Selected built-in Bloomerp resources"),
        help_text=_(
            "Stable MCP resource URIs or URI templates. Unavailable resources cannot be read. Used only for selected resource access."
        ),
    )
    mcp_integrations = models.ManyToManyField(
        "bloomerp.MCPIntegration",
        blank=True,
        related_name="ai_agents",
        verbose_name=_("External MCP integrations"),
        help_text=_(
            "Tools from enabled external integrations are available to this agent. Shared integrations use their shared connection; personal integrations require the acting user's existing connection. Missing or expired connections require reconnecting."
        ),
    )

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Name"),
        help_text=_("Display name shown in the chat agent selector."),
    )
    provider = models.CharField(
        max_length=100,
        choices=provider_choices,
        verbose_name=_("AI Provider"),
        help_text=_(
            "Registered provider used to validate settings and construct the runtime."
        ),
    )
    model_identifier = models.CharField(
        max_length=255,
        verbose_name=_("Provider Model Identifier"),
        help_text=_(
            "Model identifier accepted by the provider, separate from the display name."
        ),
    )
    default_instructions = models.TextField(
        blank=True,
        default="",
        verbose_name=_("System Instructions"),
        help_text=_(
            "Base instructions captured when a new run starts with this agent."
        ),
    )
    enabled = models.BooleanField(
        default=True,
        verbose_name=_("Enabled"),
        help_text=_("Allow permitted users to select this agent for new runs."),
    )
    credentials_encrypted = models.JSONField(
        blank=True,
        default=dict,
        editable=False,
        verbose_name=_("Encrypted Credentials"),
        help_text=_(
            "Versioned encryption metadata and encrypted provider credentials. Configure or rotate values through set_credentials; plaintext is never stored here."
        ),
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Provider Parameters"),
        help_text=_(
            "Provider-validated model controls. A max_tokens parameter limits output per response, separate from the total run token budget."
        ),
    )
    base_url = models.URLField(
        blank=True,
        null=True,
        verbose_name=_("Provider Endpoint"),
        help_text=_(
            "Optional provider API endpoint. Leave blank to use the provider default; exclude credentials and query parameters."
        ),
    )
    request_timeout_seconds = models.PositiveIntegerField(
        default=60,
        verbose_name=_("Request Timeout (Seconds)"),
        help_text=_(
            "Timeout for an individual provider request, separate from the total run duration."
        ),
    )
    max_tokens = models.PositiveIntegerField(
        default=20000,
        null=True,
        blank=True,
        verbose_name=_("Maximum Tokens per Run"),
        help_text=_(
            "Maximum total input and output tokens across all attempts of one run. Leave blank for no run token limit."
        ),
    )
    max_tool_calls = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Maximum Tool Calls per Run"),
        help_text=_(
            "Maximum cumulative tool calls across all attempts of one run. Leave blank for no tool-call limit."
        ),
    )
    max_duration_seconds = models.PositiveIntegerField(
        default=300,
        null=True,
        blank=True,
        verbose_name=_("Maximum Run Duration (Seconds)"),
        help_text=_(
            "Maximum cumulative execution time across all attempts of one run. Leave blank for no duration limit."
        ),
    )

    def __str__(self) -> str:
        """Return the user-facing model name without credentials."""
        return self.name

    def _cipher(self) -> Fernet:
        """Derive a purpose-specific encryption key from the instance's durable secret."""
        digest = salted_hmac(
            "bloomerp.ai.credentials",
            "v1",
            secret=settings.SECRET_KEY,
            algorithm="sha256",
        ).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def set_credentials(self, values: dict[str, Any]) -> None:
        """Validate and encrypt credential values before assigning persistent storage."""
        provider = AI_PROVIDER_REGISTRY.get(self.provider)
        if provider is None:
            raise ValidationError("Unknown AI provider")
        provider.credentials_schema.model_validate(values)
        # Serialize the original validated inputs, avoiding SecretStr's masked JSON.
        ciphertext = (
            self._cipher()
            .encrypt(json.dumps(values, allow_nan=False).encode())
            .decode()
        )
        self.credentials_encrypted = EncryptedCredentialsEnvelope(
            ciphertext=ciphertext
        ).model_dump(mode="json")

    def validated_credentials(
        self, provider_key: str | None = None
    ) -> AIProviderCredentialsSchema:
        """Decrypt current credentials and validate against the pinned provider schema."""
        provider = AI_PROVIDER_REGISTRY.get(provider_key or self.provider)
        if provider is None or not self.credentials_encrypted:
            raise ValidationError("Model credentials are not configured")
        try:
            envelope = EncryptedCredentialsEnvelope.model_validate(
                self.credentials_encrypted
            )
            values = json.loads(self._cipher().decrypt(envelope.ciphertext.encode()))
        except (SchemaValidationError, InvalidToken, ValueError, TypeError) as error:
            raise ValidationError(
                _("Model credentials could not be decrypted.")
            ) from error
        return provider.credentials_schema.model_validate(values)

    def runtime_credentials(self, provider_key: str) -> AgentRuntimeCredentials:
        """Resolve rotating secrets without changing the run's pinned configuration."""
        credentials = self.validated_credentials(provider_key)
        return AgentRuntimeCredentials(
            api_key=getattr(credentials, "api_key", None),
            provider_credentials=credentials,
        )

    def runtime_config(self) -> AgentRuntimeConfig:
        """Validate and snapshot all non-secret settings for a newly accepted run."""
        provider = AI_PROVIDER_REGISTRY.get(self.provider)
        if provider is None:
            raise ValidationError("Unknown AI provider")
        parameters = provider.config_schema.model_validate(self.parameters).model_dump(
            mode="json", exclude_none=True
        )
        return AgentRuntimeConfig(
            runtime=provider.runtime,
            provider=self.provider,
            model=self.model_identifier,
            model_record_id=str(self.pk),
            agent_key="bloomai",
            agent_version="1",
            instructions=self.default_instructions,
            base_url=self.base_url or None,
            request_timeout_seconds=self.request_timeout_seconds,
            parameters=parameters,
        )

    def run_budgets(self) -> RunBudgets:
        """Pin cumulative token, tool-call, and duration limits for one logical run."""
        return RunBudgets(
            max_tokens=self.max_tokens,
            max_tool_calls=self.max_tool_calls,
            max_duration_seconds=self.max_duration_seconds,
        )

    def clean(self) -> None:
        """Reject invalid provider configuration and non-positive execution limits."""
        super().clean()
        if not isinstance(self.internal_tools, list) or any(
            not isinstance(name, str) or not name.strip()
            for name in self.internal_tools
        ):
            raise ValidationError(
                {"internal_tools": _("Select a list of MCP tool names.")}
            )
        if not isinstance(self.internal_resources, list) or any(
            not isinstance(uri, str) or not uri.strip()
            for uri in self.internal_resources
        ):
            raise ValidationError(
                {
                    "internal_resources": _(
                        "Select a list of MCP resource URIs or URI templates."
                    )
                }
            )
        try:
            if self.credentials_encrypted:
                EncryptedCredentialsEnvelope.model_validate(self.credentials_encrypted)
            self.runtime_config()
            self.run_budgets()
        except (ValueError, SchemaValidationError) as error:
            raise ValidationError("Invalid AI agent configuration") from error

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate configured providers, parameters, and budgets on ordinary ORM writes."""
        self.full_clean()
        super().save(*args, **kwargs)
