"""Provider-owned PydanticAI agent construction."""

from __future__ import annotations

from typing import Self

import httpx
from anthropic import AsyncAnthropic
from pydantic import ConfigDict, Field, model_validator
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest

from .common import _api_key
from .pydantic_ai_common import PydanticAISettings


class AnthropicSettings(PydanticAISettings):
    """Validate the settings supported by the built-in Anthropic integration."""

    max_tokens: int | None = Field(
        default=4096,
        gt=0,
        strict=True,
        description="Output token limit per response. Defaults to 4096 tokens for Anthropic.",
    )

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        json_schema_extra={"form_exclude": ["seed", "openai_reasoning_effort"]},
    )

    @model_validator(mode="after")
    def validate_supported_settings(self) -> Self:
        """Reject OpenAI-only controls before an Anthropic model is contacted."""
        if self.openai_reasoning_effort is not None:
            raise ValueError("openai_reasoning_effort is not an Anthropic setting")
        if self.seed is not None:
            raise ValueError("Anthropic does not support seed")
        return self


def create_anthropic_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct an Anthropic Messages model using explicit instance credentials."""
    sdk = AsyncAnthropic(
        api_key=_api_key(credentials),
        base_url=request.config.base_url or "https://api.anthropic.com",
        http_client=client,
        max_retries=0,
    )
    return AnthropicModel(
        request.config.model, provider=AnthropicProvider(anthropic_client=sdk)
    )
