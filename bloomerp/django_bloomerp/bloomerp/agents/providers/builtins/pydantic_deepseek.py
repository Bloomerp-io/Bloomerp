"""Provider-owned PydanticAI agent construction."""

from __future__ import annotations

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest

from .common import _openai_client


def create_deepseek_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct a DeepSeek model with its provider-specific reasoning profile."""
    sdk = _openai_client(
        request, credentials, client, default_url="https://api.deepseek.com"
    )
    return OpenAIChatModel(
        request.config.model, provider=DeepSeekProvider(openai_client=sdk)
    )
