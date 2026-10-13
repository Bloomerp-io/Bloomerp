"""Outbound MCP OAuth discovery, client registration and PKCE token exchange.

Protocol reference: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
These services are unrelated to Bloomerp's inbound OAuth provider.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import secrets
import socket
import time
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils.crypto import salted_hmac
from requests.utils import parse_dict_header


class MCPAuthenticationError(Exception):
    """Expose only a safe, actionable authentication failure to the wizard."""


def wizard_cipher() -> Fernet:
    """Derive a separate encryption key for temporary wizard secrets."""
    digest = salted_hmac(
        "bloomerp.mcp.wizard", "v1", secret=settings.SECRET_KEY, algorithm="sha256"
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(values: dict[str, Any]) -> str:
    """Encrypt temporary OAuth state so even signed-cookie sessions hide secrets."""
    return (
        wizard_cipher().encrypt(json.dumps(values, allow_nan=False).encode()).decode()
    )


def unseal(value: str) -> dict[str, Any]:
    """Read encrypted wizard state while sanitizing corruption and key-change errors."""
    try:
        decoded = json.loads(wizard_cipher().decrypt(value.encode()))
        if not isinstance(decoded, dict):
            raise TypeError("Not an object")
        return decoded
    except (InvalidToken, ValueError, TypeError, AttributeError):
        raise MCPAuthenticationError(
            "Authentication state expired or is invalid. Reconnect to continue."
        ) from None


def validate_remote_url(url: str) -> httpx.URL:
    """Require HTTPS metadata and remote endpoints without credentials or fragments."""
    try:
        value = httpx.URL(url)
        if (
            value.scheme != "https"
            or not value.host
            or value.userinfo
            or value.fragment
        ):
            raise ValueError("Unsafe URL")
        return value
    except (ValueError, TypeError, httpx.InvalidURL):
        raise MCPAuthenticationError(
            "Use a remote HTTPS endpoint without embedded credentials or fragments."
        ) from None


class PublicHTTPTransport(httpx.BaseTransport):
    """Pin each connection to a public DNS result while preserving TLS verification."""

    def __init__(self) -> None:
        """Create a TLS-verified HTTP transport without environment proxy settings."""
        self.transport = httpx.HTTPTransport(trust_env=False)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Reject private targets and DNS rebinding before making a pinned request."""
        url = validate_remote_url(str(request.url))
        try:
            results = socket.getaddrinfo(
                url.host, url.port or 443, type=socket.SOCK_STREAM
            )
            addresses = [ipaddress.ip_address(result[4][0]) for result in results]
            if not addresses or any(not address.is_global for address in addresses):
                raise ValueError("Private destination")
        except (OSError, ValueError):
            raise MCPAuthenticationError(
                "The server must resolve to a public network address."
            ) from None
        headers = request.headers.copy()
        headers["Host"] = url.netloc.decode()
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=str(addresses[0])),
            headers=headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": url.host},
        )
        return self.transport.handle_request(pinned)

    def close(self) -> None:
        """Close any outbound connections owned by this transport."""
        self.transport.close()


def remote_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    read_body: bool = True,
) -> httpx.Response:
    """Issue one bounded public HTTPS request without redirects or secret logging."""
    validate_remote_url(url)
    started_at = time.monotonic()
    try:
        with (
            httpx.Client(
                transport=PublicHTTPTransport(),
                timeout=10,
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream(
                method,
                url,
                headers={"Accept-Encoding": "identity", **(headers or {})},
                data=data,
                json=payload,
            ) as response,
        ):
            content = bytearray()
            if read_body:
                if (
                    response.headers.get("Content-Encoding", "identity").lower()
                    != "identity"
                ):
                    raise MCPAuthenticationError(
                        "The server ignored the requested uncompressed authentication response."
                    )
                for chunk in response.iter_raw():
                    if time.monotonic() - started_at > 20:
                        raise MCPAuthenticationError(
                            "The authentication response took too long. Try again."
                        )
                    content.extend(chunk)
                    if len(content) > 1_048_576:
                        raise MCPAuthenticationError(
                            "The server returned an oversized authentication response."
                        )
            response_headers = dict(response.headers)
            response_headers.pop("content-encoding", None)
            return httpx.Response(
                response.status_code,
                headers=response_headers,
                content=bytes(content),
                request=response.request,
            )
    except (httpx.HTTPError, OSError):
        raise MCPAuthenticationError(
            "The authentication server could not be reached. Check the endpoint and try again."
        ) from None


def response_object(response: httpx.Response) -> dict[str, Any]:
    """Read successful JSON metadata without reflecting remote errors or token values."""
    try:
        value = response.json()
        if not response.is_success or not isinstance(value, dict):
            raise ValueError("Unsuccessful metadata")
        return value
    except (ValueError, TypeError):
        raise MCPAuthenticationError(
            "The server returned invalid authentication metadata or rejected the request."
        ) from None


def discover(endpoint: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Discover RFC9728 resource metadata and RFC8414/OIDC server metadata."""
    url = validate_remote_url(endpoint)
    probe = remote_request(
        "GET",
        endpoint,
        headers={"Accept": "application/json, text/event-stream"},
        read_body=False,
    )
    challenge = probe.headers.get("www-authenticate", "")
    bearer = re.search(r"(?:^|,)\s*Bearer\s+", challenge, flags=re.IGNORECASE)
    parameters = (
        parse_dict_header(challenge[bearer.end() :]) if bearer is not None else {}
    )
    resource_urls = (
        [parameters["resource_metadata"]]
        if parameters.get("resource_metadata")
        else [
            str(
                url.copy_with(
                    path="/.well-known/oauth-protected-resource" + url.path, query=None
                )
            ),
            str(
                url.copy_with(path="/.well-known/oauth-protected-resource", query=None)
            ),
        ]
    )
    resource: dict[str, Any] | None = None
    for metadata_url in dict.fromkeys(resource_urls):
        response = remote_request("GET", metadata_url)
        if response.is_success:
            resource = response_object(response)
            break
    if not resource or resource.get("resource") != endpoint:
        raise MCPAuthenticationError(
            "The server has no matching OAuth protected-resource metadata."
        )
    issuers = resource.get("authorization_servers")
    if not isinstance(issuers, list) or not issuers or not isinstance(issuers[0], str):
        raise MCPAuthenticationError(
            "The server does not advertise an OAuth authorization server."
        )
    issuer = issuers[0]
    issuer_url = validate_remote_url(issuer)
    if issuer_url.query:
        raise MCPAuthenticationError(
            "The authorization issuer must not contain query parameters."
        )
    path = issuer_url.path.rstrip("/")
    metadata_urls = [
        str(
            issuer_url.copy_with(path="/.well-known/oauth-authorization-server" + path)
        ),
        str(issuer_url.copy_with(path="/.well-known/openid-configuration" + path)),
        str(issuer_url.copy_with(path=path + "/.well-known/openid-configuration")),
    ]
    for metadata_url in dict.fromkeys(metadata_urls):
        response = remote_request("GET", metadata_url)
        if not response.is_success:
            continue
        metadata = response_object(response)
        if metadata.get("issuer") != issuer:
            raise MCPAuthenticationError(
                "The authorization server issuer does not match discovery."
            )
        pkce_methods = metadata.get("code_challenge_methods_supported")
        if not isinstance(pkce_methods, list) or "S256" not in pkce_methods:
            raise MCPAuthenticationError(
                "The authorization server must support PKCE S256."
            )
        for key in ("authorization_endpoint", "token_endpoint"):
            validate_remote_url(metadata.get(key, ""))
        return resource, metadata, str(parameters.get("scope") or "")
    raise MCPAuthenticationError(
        "The authorization server does not provide supported OAuth discovery metadata."
    )


def client_metadata(client_id: str, callback_url: str) -> dict[str, Any]:
    """Describe this public PKCE client for metadata documents and registration."""
    return {
        "client_id": client_id,
        "client_name": "Bloomerp MCP integrations",
        "redirect_uris": [callback_url],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "native"
        if urlsplit(callback_url).hostname in {"localhost", "127.0.0.1", "::1"}
        else "web",
    }


def begin_authorization(
    endpoint: str,
    callback_url: str,
    metadata_url: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    scopes: str = "",
    owner_id: str,
) -> tuple[str, dict[str, Any]]:
    """Select client registration, discover scopes and construct a state-bound PKCE redirect."""
    callback = urlsplit(callback_url)
    if callback.scheme != "https" and not (
        callback.scheme == "http"
        and callback.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise MCPAuthenticationError(
            "OAuth requires an HTTPS callback URL, or localhost for development."
        )
    resource, metadata, challenged_scope = discover(endpoint)
    registration: dict[str, Any] = {}
    if not client_id:
        if metadata.get(
            "client_id_metadata_document_supported"
        ) is True and metadata_url.startswith("https://"):
            client_id = metadata_url
        elif metadata.get("registration_endpoint"):
            registration = response_object(
                remote_request(
                    "POST",
                    metadata["registration_endpoint"],
                    payload={
                        key: value
                        for key, value in client_metadata("", callback_url).items()
                        if key != "client_id"
                    },
                )
            )
            client_id = registration.get("client_id", "")
            client_secret = registration.get("client_secret", "")
        else:
            raise MCPAuthenticationError(
                "This server requires a pre-registered OAuth client ID. Register the displayed callback URL and enter its client ID."
            )
    if not isinstance(client_id, str) or not client_id:
        raise MCPAuthenticationError(
            "The authorization server did not register an OAuth client."
        )
    if not isinstance(client_secret, str):
        raise MCPAuthenticationError(
            "The server returned an invalid OAuth client secret."
        )
    methods = metadata.get(
        "token_endpoint_auth_methods_supported", ["client_secret_basic"]
    )
    if not isinstance(methods, list) or not all(
        isinstance(value, str) for value in methods
    ):
        raise MCPAuthenticationError(
            "The server returned invalid client authentication metadata."
        )
    if (
        not client_secret
        and "none" not in methods
        and any(
            method in methods
            for method in ("client_secret_basic", "client_secret_post")
        )
    ):
        raise MCPAuthenticationError(
            "This server requires a confidential OAuth client. Enter its pre-registered client ID and client secret."
        )
    method = registration.get("token_endpoint_auth_method")
    if method is not None and not isinstance(method, str):
        raise MCPAuthenticationError(
            "The server returned an invalid OAuth client authentication method."
        )
    if method is None:
        method = (
            "client_secret_basic"
            if client_secret and "client_secret_basic" in methods
            else "client_secret_post"
            if client_secret and "client_secret_post" in methods
            else "none"
        )
    if (
        method not in {"none", "client_secret_basic", "client_secret_post"}
        or method not in methods
    ):
        raise MCPAuthenticationError(
            "The server requires an unsupported OAuth client authentication method."
        )
    if method != "none" and not client_secret:
        raise MCPAuthenticationError(
            "Enter the client secret for this registered OAuth client."
        )
    supported_scopes = resource.get("scopes_supported", [])
    if not isinstance(supported_scopes, list) or not all(
        isinstance(value, str) for value in supported_scopes
    ):
        raise MCPAuthenticationError(
            "The server returned invalid OAuth scope metadata."
        )
    scope = challenged_scope or scopes or " ".join(supported_scopes)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    parameters = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback_url,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": endpoint,
    }
    if scope:
        parameters["scope"] = scope
    auth_url = urlsplit(metadata["authorization_endpoint"])
    query = dict(parse_qsl(auth_url.query)) | parameters
    location = urlunsplit(
        (auth_url.scheme, auth_url.netloc, auth_url.path, urlencode(query), "")
    )
    pending = {
        "state": state,
        "verifier": verifier,
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_method": method,
        "token_endpoint": metadata["token_endpoint"],
        "issuer": metadata["issuer"],
        "require_issuer": metadata.get("authorization_response_iss_parameter_supported")
        is True,
        "callback_url": callback_url,
        "resource": endpoint,
        "scope": scope,
        "owner_id": owner_id,
        "started_at": time.time(),
    }
    return location, pending


def exchange_code(pending: dict[str, Any], code: str) -> dict[str, Any]:
    """Exchange an authorization code with PKCE and the exact resource and redirect URI."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending["callback_url"],
        "code_verifier": pending["verifier"],
        "resource": pending["resource"],
        "client_id": pending["client_id"],
    }
    headers = {"Accept": "application/json"}
    if pending["auth_method"] == "client_secret_basic":
        # OAuth Basic authentication percent-encodes each component before Base64.
        encoded = (
            quote_plus(pending["client_id"])
            + ":"
            + quote_plus(pending["client_secret"])
        )
        headers["Authorization"] = (
            "Basic " + base64.b64encode(encoded.encode()).decode()
        )
        data.pop("client_id")
    elif pending["auth_method"] == "client_secret_post":
        data["client_secret"] = pending["client_secret"]
    tokens = response_object(
        remote_request("POST", pending["token_endpoint"], data=data, headers=headers)
    )
    if (
        str(tokens.get("token_type", "")).lower() != "bearer"
        or not isinstance(tokens.get("access_token"), str)
        or not tokens["access_token"].strip()
    ):
        raise MCPAuthenticationError(
            "The authorization server did not issue a usable bearer token."
        )
    values = {
        key: tokens[key] for key in ("access_token", "refresh_token") if tokens.get(key)
    }
    values["client_id"] = pending["client_id"]
    values["issuer"] = pending["issuer"]
    if pending.get("client_secret"):
        values["client_secret"] = pending["client_secret"]
    expires_at = None
    if "expires_in" in tokens:
        try:
            lifetime = int(tokens["expires_in"])
            if lifetime <= 0:
                raise ValueError("Expired token")
            expires_at = time.time() + lifetime
        except (ValueError, TypeError, OverflowError):
            raise MCPAuthenticationError(
                "The authorization server returned an invalid token expiry."
            ) from None
    return {
        "credentials": values,
        "expires_at": expires_at,
        "scope": tokens.get("scope", pending["scope"]),
    }


def verify_api_key(endpoint: str, api_key: str) -> str:
    """Check HTTP authentication without invoking MCP tools or claiming unverified access."""
    response = remote_request(
        "GET",
        endpoint,
        headers={
            "Authorization": "Bearer " + api_key,
            "Accept": "application/json, text/event-stream",
        },
        read_body=False,
    )
    if response.status_code in {401, 403}:
        raise MCPAuthenticationError(
            "The server rejected this API key or its access permissions."
        )
    if response.is_success:
        return "ready"
    if response.status_code == 405:
        return "pending"
    raise MCPAuthenticationError(
        "The server could not verify the API key. Check the endpoint and try again."
    )
