"""Shared settings and identifiers for Bloomerp's OAuth provider."""

import hashlib

from django.http import HttpRequest
from django.urls import reverse

from bloomerp.config.definition import get_bloomerp_config

MCP_SCOPE = "mcp:tools"
CLIENT_PREFIX = "blp_oauth_client_"
TOKEN_PREFIX = "blp_oauth_"


def oauth_enabled() -> bool:
    """Return whether this instance explicitly enables its OAuth provider."""
    return get_bloomerp_config().auth.oauth.enabled


def oauth_resource(request: HttpRequest) -> str:
    """Build the canonical audience URI of this instance's MCP endpoint."""
    return request.build_absolute_uri(reverse("mcp"))


def oauth_issuer(request: HttpRequest) -> str:
    """Build the OAuth issuer identifier on this Django origin."""
    return request.build_absolute_uri("/").rstrip("/")


def oauth_metadata_url(request: HttpRequest) -> str:
    """Build the protected-resource discovery URL for bearer challenges."""
    return request.build_absolute_uri(reverse("oauth_resource_metadata"))


def hash_oauth_secret(value: str) -> str:
    """Hash a high-entropy OAuth secret before database storage or lookup."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
