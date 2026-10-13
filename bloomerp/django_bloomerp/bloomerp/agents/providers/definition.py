"""Extensible AI providers and typed execution-time credentials."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from bloomerp.agents.runtime import AgentRuntime, AgentRuntimeConfig


class AIProviderCredentialsSchema(BaseModel):
    """Validate provider credentials without including them in public serialization."""

    model_config = ConfigDict(extra="forbid")


class DefaultAIProviderCredentialsSchema(AIProviderCredentialsSchema):
    """Require an explicit API key for the built-in remote providers."""

    api_key: SecretStr


class AIProviderDefinition(BaseModel):
    """Bind a stable provider key to its fresh runtime factory and schema classes."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(
        default="",
        description="User-facing explanation shown when choosing this provider.",
    )
    runtime: str = "pydantic_ai"
    runtime_factory: Callable[[AgentRuntimeConfig], AgentRuntime]
    credentials_schema: type[AIProviderCredentialsSchema] = (
        DefaultAIProviderCredentialsSchema
    )
    config_schema: type[BaseModel]
    integration: Any = None
    model_identifier_factory: (
        Callable[[AIProviderCredentialsSchema, str | None], list[tuple[str, str]]]
        | None
    ) = None


AIProviderDefintion = AIProviderDefinition
