"""Provider-owned PydanticAI agent construction."""

from __future__ import annotations

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest

from .common import _openai_client


def create_openai_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct an OpenAI Responses model using the instance configuration."""
    provider = OpenAIProvider(
        openai_client=_openai_client(request, credentials, client)
    )
    return OpenAIResponsesModel(request.config.model, provider=provider)


def create_openai_chat_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct a Chat Completions model, including configured compatible endpoints."""
    provider = OpenAIProvider(
        openai_client=_openai_client(request, credentials, client)
    )
    return OpenAIChatModel(request.config.model, provider=provider)
