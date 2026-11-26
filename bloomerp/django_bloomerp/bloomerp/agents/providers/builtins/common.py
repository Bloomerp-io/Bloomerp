"""Explicit credentials and owned SDK clients for built-in providers."""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI

from bloomerp.agents.definition import ModelModalities, ModelModality
from bloomerp.agents.providers.definition import (
    AIProviderCredentialsSchema,
    DefaultAIProviderCredentialsSchema,
)
from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest


def _catalog_model_modalities(
    model_identifier: str,
    credentials: AIProviderCredentialsSchema,
    *,
    catalog_url: str,
    params: dict[str, str] | None = None,
    architecture_key: str | None = None,
) -> ModelModalities | None:
    """Normalize the selected model's declared modalities from a provider catalog."""
    try:
        key = DefaultAIProviderCredentialsSchema.model_validate(
            credentials.model_dump()
        ).api_key.get_secret_value()
        response = httpx.get(
            catalog_url,
            params=params,
            headers={"Authorization": f"Bearer {key}"},
            timeout=5,
        )
        response.raise_for_status()
        for model in response.json()["data"]:
            if model["id"] != model_identifier:
                continue
            metadata = model[architecture_key] if architecture_key else model
            inputs = metadata["input_modalities"]
            outputs = metadata["output_modalities"]
            if isinstance(inputs, list) and isinstance(outputs, list):
                return ModelModalities(
                    input=tuple(item for item in ModelModality if item in inputs),
                    output=tuple(item for item in ModelModality if item in outputs),
                )
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None
    return None


def _api_key(credentials: AgentRuntimeCredentials) -> str:
    """Require explicit API credentials for the built-in remote providers."""
    if credentials.api_key is None or not credentials.api_key.get_secret_value():
        raise ValueError("This provider requires explicitly resolved API credentials")
    return credentials.api_key.get_secret_value()


def _openai_client(
    request: AgentRuntimeRunRequest,
    credentials: AgentRuntimeCredentials,
    client: httpx.AsyncClient,
    *,
    default_url: str = "https://api.openai.com/v1",
) -> AsyncOpenAI:
    """Build a compatible SDK client without ambient API keys or endpoint defaults."""
    return AsyncOpenAI(
        api_key=_api_key(credentials),
        base_url=request.config.base_url or default_url,
        http_client=client,
        max_retries=0,
    )
