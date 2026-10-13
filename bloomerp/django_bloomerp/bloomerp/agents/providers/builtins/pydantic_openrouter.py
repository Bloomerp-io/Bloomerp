"""OpenRouter model construction using the existing PydanticAI runtime."""

from __future__ import annotations

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest

from .common import _openai_client


def create_openrouter_model(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
) -> Model:
    """Build an OpenRouter model with explicit credentials and an owned client.

    Model identifiers are configured by the instance, not discovered remotely.
    The installed SDK supplies OpenRouter's model profiles and message handling;
    available tools, structured outputs and settings still depend on the model.
    """
    vendor, separator, model = request.config.model.partition("/")
    if not separator or not vendor.strip() or not model.strip():
        raise ValueError(
            "OpenRouter model identifiers must use the vendor/model format"
        )
    if credentials.api_key is None or not credentials.api_key.get_secret_value():
        raise ValueError("OpenRouter requires an API key in the agent's credentials")
    sdk = _openai_client(
        request, credentials, client, default_url="https://openrouter.ai/api/v1"
    )
    return OpenRouterModel(
        request.config.model, provider=OpenRouterProvider(openai_client=sdk)
    )
