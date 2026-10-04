"""Validated model controls shared by built-in PydanticAI providers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import Field
from pydantic_ai.models import Model

from bloomerp.agents.runtime import (
    AgentRuntimeCredentials,
    AgentRuntimePayload,
    AgentRuntimeRunRequest,
)


class PydanticAISettings(AgentRuntimePayload):
    """Allow documented model controls without bypassing the tool/secret boundary.

    ``max_tokens`` is a per-response output cap, separate from the run's token
    budget. Provider-specific settings can be added deliberately as needed.
    Arbitrary headers, request bodies, and provider-hosted tools are not accepted.
    """

    max_tokens: int | None = Field(
        default=None,
        gt=0,
        strict=True,
        description="Output token limit per response. Leave blank for the provider default.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Sampling temperature from 0 to 2. Leave blank for the model default; reasoning models may not support this control.",
    )
    top_p: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Nucleus sampling probability from 0 to 1. Leave blank for the model default.",
    )
    parallel_tool_calls: bool | None = Field(
        default=None,
        strict=True,
        description="Allow multiple tool calls in one response, or use the provider default.",
    )
    seed: int | None = Field(
        default=None,
        strict=True,
        description="Optional deterministic sampling seed, where supported by the model.",
    )
    stop_sequences: list[str] | None = Field(
        default=None,
        description="Stop generation when one of these strings is reached. Enter one string per line.",
    )
    openai_reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    ) = Field(
        default=None,
        description="Reasoning effort for compatible OpenAI agents. Leave blank for the model default.",
    )


type ModelFactory = Callable[
    [AgentRuntimeRunRequest, AgentRuntimeCredentials, httpx.AsyncClient], Model
]


@dataclass(frozen=True)
class PydanticAIProvider:
    """Register a model factory and its typed settings for one provider identifier.

    Factories receive the request, explicit credentials, and an attempt-owned HTTP
    client. They must return a PydanticAI Agent, avoid global credential defaults,
    and use the supplied client or manage their own resources. Settings subclasses
    can add validated provider-specific options without modifying the runtime.
    """

    factory: ModelFactory
    settings_schema: type[PydanticAISettings] = PydanticAISettings
