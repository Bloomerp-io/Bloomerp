"""Shared model configuration with encrypted, non-public execution credentials."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from collections.abc import Sequence
from os import PathLike
from typing import Any, BinaryIO, Literal, cast, overload
from uuid import uuid4

import httpx
from asgiref.sync import async_to_sync, sync_to_async
from cryptography.fernet import Fernet, InvalidToken
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from django.utils.crypto import salted_hmac
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext_noop
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as SchemaValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from bloomerp.agents.definition import ModelModalities, ModelModality, RunBudgets
from bloomerp.agents.providers.definition import AIProviderCredentialsSchema
from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY, provider_choices
from bloomerp.agents.runtime import (
    AgentRuntimeConfig,
    AgentRuntimeContext,
    AgentRuntimeCredentials,
    AgentRuntimeRunRequest,
)
from bloomerp.agents.runtimes.pydantic_ai import create_model, supports_attachment
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.field_types.registry import FieldContext
from bloomerp.field_types.utils.widget_factories import widget
from bloomerp.form_fields.mapping_field import MappingField
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
    DetailTab,
    DetailTabsConfiguration,
    DetailViewSettings,
    FieldLayout,
    FieldSettings,
    LayoutItem,
    LayoutRow,
    ModelViewSettings,
)
from bloomerp.modules.bloomai import BloomAIModule
from bloomerp.widgets.mapping_widget import MappingWidget

from .base import agent_search_settings

type InvocationFile = str | PathLike[str] | BinaryIO | File

_MODALITY_DIRECTIONS = [("input", _("Input")), ("output", _("Output"))]
_MODALITY_CHOICES = [(modality.value, modality.value) for modality in ModelModality]
_MODALITY_DEFAULTS = ModelModalities().model_dump(mode="json")


def _model_modalities_widget(context: FieldContext) -> MappingWidget:
    """Build fixed Input and Output rows with a multi-select for each direction."""
    return MappingWidget(
        attrs=dict(context.attrs),
        left=_MODALITY_DIRECTIONS,
        left_widget=forms.HiddenInput(),
        right_widget=forms.SelectMultiple(choices=_MODALITY_CHOICES),
        allow_adding_groups=False,
        fixed_initial_values=_MODALITY_DEFAULTS,
    )


class _ModelModalitiesField(MappingField):
    """Compare each direction's selections independently of checkbox order."""

    def has_changed(self, initial: Any, data: Any) -> bool:
        """Compare effective capabilities, including defaults for omitted directions."""
        if self.disabled:
            return False
        try:
            before = self.to_python(initial)
            after = self.to_python(data)
        except ValidationError:
            return True
        return any(
            set(before.get(key, defaults)) != set(after.get(key, defaults))
            for key, defaults in _MODALITY_DEFAULTS.items()
        )


def model_modalities_form_field(
    context: FieldContext,
    default: forms.Field | None,
) -> MappingField:
    """Clean indexed rows and legacy JSON into the agent's modality mapping."""
    return _ModelModalitiesField(
        left=_MODALITY_DIRECTIONS,
        right_field=forms.MultipleChoiceField(
            choices=_MODALITY_CHOICES, required=False
        ),
        keep_empty_fixed_values=True,
        widget=_model_modalities_widget(context),
        required=default.required if default else False,
        label=default.label if default else _("Model modalities"),
        initial=default.initial if default else None,
        help_text=_("Select the supported input and output modalities."),
    )


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
        model_view_settings=ModelViewSettings(
            default_dataviews=[
                TableDataView(
                    name=gettext_noop("AI agents"),
                    display_fields=["name", "provider", "model_identifier", "enabled"],
                    sort_field="name",
                )
            ]
        ),
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
        string_search_settings=agent_search_settings(
            allow_global_search=True,
            include_search_routes=True,
        ),
        field_settings=[
            FieldSettings(
                field="default_instructions",
                widget_factory=widget(forms.Textarea, attrs={"rows": 4}),
            ),
            FieldSettings(
                field="modalities",
                form_factory=model_modalities_form_field,
                widget_factory=_model_modalities_widget,
            ),
        ],
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
    modalities = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Model modalities"),
        help_text=_(
            "Supported model inputs and outputs. Defaults to text in both directions."
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
            modalities=ModelModalities.model_validate(self.modalities)
            if self.modalities != {}
            else None,
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

    @overload
    def invoke(
        self,
        input_text: str,
        *,
        files: Sequence[InvocationFile] = (),
        output_schema: None = None,
    ) -> str:
        """Return the model's plain-text response to a prompt and optional files."""

    @overload
    def invoke[OutputT: BaseModel](
        self,
        input_text: str,
        *,
        files: Sequence[InvocationFile] = (),
        output_schema: type[OutputT],
    ) -> OutputT:
        """Return a response validated against the supplied Pydantic model class."""

    def invoke[OutputT: BaseModel](
        self,
        input_text: str,
        *,
        files: Sequence[InvocationFile] = (),
        output_schema: type[OutputT] | None = None,
    ) -> str | OutputT:
        """Run a stateless prompt synchronously with the configured PydanticAI provider.

        This model-only call uses an ephemeral system context for trusted
        server-side callers. Pass authorized filesystem paths or open, seekable
        binary files with a filename or content type. Files are sent as model
        inputs. Pass a Pydantic model class to get a validated instance.
        """
        if not self.enabled:
            raise ValidationError(_("This AI agent is disabled."))

        config = self.runtime_config()
        if config.runtime != "pydantic_ai":
            raise ValidationError(
                _("Direct invocation requires a PydanticAI provider.")
            )

        credentials = self.runtime_credentials(config.provider)
        request = AgentRuntimeRunRequest(
            run_id=uuid4(),
            attempt_id=uuid4(),
            config=config,
            context=AgentRuntimeContext(user_id="system", conversation_id=uuid4()),
            budgets=self.run_budgets(),
        )

        def build_file_prompt(model: Model) -> list[str | BinaryContent]:
            """Read bounded, supported files while preserving each stream's position."""
            modalities = config.modalities or ModelModalities()
            remaining = getattr(
                settings, "BLOOMERP_AGENT_UPLOAD_MAX_BYTES", 20 * 1024 * 1024
            )
            prompt: list[str | BinaryContent] = [input_text] if input_text else []
            for file in files:
                path = file if isinstance(file, (str, PathLike)) else None
                name = path if path is not None else getattr(file, "name", None)
                media_type = (
                    (getattr(file, "content_type", None) or "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if not media_type or media_type == "application/octet-stream":
                    media_type = (
                        mimetypes.guess_type(name)[0]
                        if isinstance(name, (str, PathLike))
                        else None
                    )
                if (
                    not media_type
                    or not modalities.accepts_attachment(media_type)
                    or not supports_attachment(model, media_type)
                ):
                    raise ValidationError(
                        _("This AI agent cannot accept %(type)s files.")
                        % {
                            "type": media_type or _("unknown"),
                        }
                    )
                if isinstance(file, (str, PathLike)):
                    with open(file, "rb") as source:
                        data = source.read(remaining + 1)
                else:
                    position = file.tell()
                    try:
                        file.seek(0)
                        data = file.read(remaining + 1)
                    finally:
                        file.seek(position)
                if not isinstance(data, bytes) or not data:
                    raise ValidationError(_("Pass a non-empty binary file."))
                if len(data) > remaining:
                    raise ValidationError(
                        _("The files exceed the agent attachment size limit.")
                    )
                prompt.append(BinaryContent(data=data, media_type=media_type))
                remaining -= len(data)
            return prompt

        async def run_prompt() -> str | OutputT:
            """Run the prompt with a scoped HTTP client and the configured budgets."""
            timeout = config.request_timeout_seconds
            async with (
                asyncio.timeout(request.budgets.max_duration_seconds),
                httpx.AsyncClient(timeout=timeout) as client,
            ):
                model = create_model(request, credentials, client)
                prompt = (
                    await sync_to_async(build_file_prompt)(model)
                    if files
                    else input_text
                )
                agent: Agent[None, str | OutputT] = Agent(
                    model,
                    instructions=config.instructions,
                    output_type=str if output_schema is None else output_schema,
                    model_settings=cast(
                        ModelSettings, {**config.parameters, "timeout": timeout}
                    ),
                    instrument=False,
                )
                result = await agent.run(
                    prompt,
                    usage_limits=UsageLimits(
                        total_tokens_limit=request.budgets.max_tokens,
                    ),
                )
                return result.output

        return async_to_sync(run_prompt)()
