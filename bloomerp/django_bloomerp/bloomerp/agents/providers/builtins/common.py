"""Explicit credentials and owned SDK clients for built-in providers."""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI

from bloomerp.agents.runtime import AgentRuntimeCredentials, AgentRuntimeRunRequest


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
