"""Provider-owned PydanticAI agent construction."""

from __future__ import annotations

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from bloomerp.agents.definition import ModelModalities
from bloomerp.agents.providers.definition import AIProviderCredentialsSchema
from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest

from .common import _catalog_model_modalities, _openai_client

DEEPSEEK_API = "https://api.deepseek.com"


def discover_deepseek_modalities(
    model_identifier: str,
    credentials: AIProviderCredentialsSchema,
    base_url: str | None,
) -> ModelModalities | None:
    """Read the selected model's advertised modalities from DeepSeek's catalog."""
    if base_url and base_url.rstrip("/") not in {DEEPSEEK_API, f"{DEEPSEEK_API}/v1"}:
        return None
    return _catalog_model_modalities(
        model_identifier, credentials, catalog_url=f"{DEEPSEEK_API}/models"
    )


def create_deepseek_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Construct a DeepSeek model with its provider-specific reasoning profile."""
    sdk = _openai_client(request, credentials, client, default_url=DEEPSEEK_API)
    return OpenAIChatModel(
        request.config.model, provider=DeepSeekProvider(openai_client=sdk)
    )
