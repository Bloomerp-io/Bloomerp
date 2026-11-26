"""OpenRouter model construction using the existing PydanticAI runtime."""

from __future__ import annotations

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from bloomerp.agents.definition import ModelModalities
from bloomerp.agents.providers.definition import AIProviderCredentialsSchema
from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest

from .common import _catalog_model_modalities, _openai_client

OPENROUTER_API = "https://openrouter.ai/api/v1"


def discover_openrouter_modalities(
    model_identifier: str,
    credentials: AIProviderCredentialsSchema,
    base_url: str | None,
) -> ModelModalities | None:
    """Read the selected model's input and output modes from OpenRouter's catalog."""
    if base_url and base_url.rstrip("/") != OPENROUTER_API:
        return None
    return _catalog_model_modalities(
        model_identifier,
        credentials,
        catalog_url=f"{OPENROUTER_API}/models",
        params={"output_modalities": "all"},
        architecture_key="architecture",
    )


def create_openrouter_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Build an OpenRouter model with explicit credentials and an owned client.

    The installed SDK supplies OpenRouter's model profiles and message handling.
    """
    vendor, separator, model = request.config.model.partition("/")
    if not separator or not vendor.strip() or not model.strip():
        raise ValueError(
            "OpenRouter model identifiers must use the vendor/model format"
        )
    if credentials.api_key is None or not credentials.api_key.get_secret_value():
        raise ValueError("OpenRouter requires an API key in the agent's credentials")
    sdk = _openai_client(request, credentials, client, default_url=OPENROUTER_API)
    return OpenRouterModel(
        request.config.model, provider=OpenRouterProvider(openai_client=sdk)
    )
