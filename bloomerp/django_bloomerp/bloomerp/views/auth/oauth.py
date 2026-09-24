"""OAuth discovery, registration, consent, and token exchange views."""

import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from bloomerp.models.auth.oauth import OAuthAccessToken, OAuthAuthorizationCode
from bloomerp.oauth import (
    CLIENT_PREFIX, MCP_SCOPE, TOKEN_PREFIX, hash_oauth_secret, oauth_enabled,
    oauth_issuer, oauth_resource,
)
from bloomerp.router import router

CHATGPT_CALLBACK = re.compile(
    r"^/(?:connector_platform_oauth_redirect|connector/oauth/[A-Za-z0-9_-]+)$"
)


def _json_error(error: str, status: int = 400) -> JsonResponse:
    """Return an OAuth-formatted error without caching it."""
    response = JsonResponse({"error": error}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def _enabled_or_404() -> bool:
    """Keep the optional provider undiscoverable until explicitly enabled."""
    return oauth_enabled()


def _valid_redirect_uri(uri: str) -> bool:
    """Allow only ChatGPT's documented HTTPS OAuth callback URLs."""
    parsed = urlsplit(uri)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "chatgpt.com"
        and not parsed.query
        and not parsed.fragment
        and bool(CHATGPT_CALLBACK.fullmatch(parsed.path))
    )


def _client_redirects(client_id: str) -> list[str] | None:
    """Verify a stateless registered public client and return its redirects."""
    if not client_id.startswith(CLIENT_PREFIX):
        return None
    try:
        data = signing.loads(client_id[len(CLIENT_PREFIX):], salt="bloomerp.oauth.client")
    except signing.BadSignature:
        return None
    redirects = data.get("redirect_uris") if isinstance(data, dict) else None
    if not isinstance(redirects, list) or not redirects:
        return None
    if not all(isinstance(uri, str) and _valid_redirect_uri(uri) for uri in redirects):
        return None
    return redirects


@router.register(re_path=r"^\.well-known/oauth-protected-resource$", route_type="api", url_name="oauth_resource_metadata")
def protected_resource_metadata(request: HttpRequest) -> HttpResponse:
    """Advertise the MCP resource and its same-origin OAuth issuer."""
    if not _enabled_or_404():
        return HttpResponse(status=404)
    return JsonResponse({
        "resource": oauth_resource(request),
        "authorization_servers": [oauth_issuer(request)],
        "scopes_supported": [MCP_SCOPE],
    })


@router.register(re_path=r"^\.well-known/oauth-protected-resource/mcp$", route_type="api", url_name="oauth_resource_metadata_mcp")
def protected_resource_metadata_mcp(request: HttpRequest) -> HttpResponse:
    """Expose path-specific discovery for clients that probe the MCP path."""
    return protected_resource_metadata(request)


@router.register(re_path=r"^\.well-known/oauth-authorization-server$", route_type="api", url_name="oauth_server_metadata")
def authorization_server_metadata(request: HttpRequest) -> HttpResponse:
    """Advertise the PKCE-enabled authorization server to MCP clients."""
    if not _enabled_or_404():
        return HttpResponse(status=404)
    return JsonResponse({
        "issuer": oauth_issuer(request),
        "authorization_endpoint": request.build_absolute_uri(reverse("oauth_authorize")),
        "token_endpoint": request.build_absolute_uri(reverse("oauth_token")),
        "registration_endpoint": request.build_absolute_uri(reverse("oauth_register")),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [MCP_SCOPE],
    })


@router.register(re_path=r"^oauth/register$", route_type="api", url_name="oauth_register")
@csrf_exempt
def register_client(request: HttpRequest) -> HttpResponse:
    """Register a public ChatGPT client with allowlisted callback URIs."""
    if not _enabled_or_404():
        return HttpResponse(status=404)
    if request.method != "POST":
        return HttpResponse(status=405)
    if len(request.body) > 8192:
        return _json_error("invalid_client_metadata")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return _json_error("invalid_client_metadata")
    if not isinstance(data, dict):
        return _json_error("invalid_client_metadata")
    redirects = data.get("redirect_uris")
    if (
        not isinstance(redirects, list)
        or not 1 <= len(redirects) <= 3
        or not all(isinstance(uri, str) and _valid_redirect_uri(uri) for uri in redirects)
        or data.get("token_endpoint_auth_method", "none") != "none"
    ):
        return _json_error("invalid_client_metadata")
    client_id = CLIENT_PREFIX + signing.dumps(
        {"redirect_uris": redirects}, salt="bloomerp.oauth.client", compress=True
    )
    response = JsonResponse({
        "client_id": client_id,
        "redirect_uris": redirects,
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }, status=201)
    response["Cache-Control"] = "no-store"
    return response


def _authorization_parameters(request: HttpRequest) -> dict[str, str] | None:
    """Validate client, audience, scope, and mandatory S256 PKCE parameters."""
    source = request.GET
    values = {key: source.get(key, "") for key in (
        "client_id", "redirect_uri", "resource", "scope", "state", "code_challenge"
    )}
    redirects = _client_redirects(values["client_id"])
    if (
        redirects is None
        or values["redirect_uri"] not in redirects
        or values["resource"] != oauth_resource(request)
        or values["scope"] not in ("", MCP_SCOPE)
        or source.get("response_type") != "code"
        or source.get("code_challenge_method") != "S256"
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", values["code_challenge"])
    ):
        return None
    values["scope"] = MCP_SCOPE
    return values


def _callback(uri: str, values: dict[str, str]) -> HttpResponse:
    """Redirect only to a previously validated client callback."""
    parsed = urlsplit(uri)
    query = urlencode([*parse_qsl(parsed.query), *values.items()])
    return redirect(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, "")))


@router.register(re_path=r"^oauth/authorize$", route_type="api", url_name="oauth_authorize")
@csrf_protect
def authorize(request: HttpRequest) -> HttpResponse:
    """Ask the signed-in user to approve one MCP-scoped OAuth grant."""
    if not _enabled_or_404():
        return HttpResponse(status=404)
    if request.method not in ("GET", "POST"):
        return HttpResponse(status=405)
    values = _authorization_parameters(request)
    if values is None:
        return _json_error("invalid_request")
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
    if request.method == "GET":
        csrf_token = get_token(request)
        body = format_html(
            "<h1>Connect ChatGPT to Bloomerp?</h1>"
            "<p>Signed in as {}. ChatGPT will be able to call Bloomerp MCP tools "
            "using your existing permissions, including tools that can change data.</p>"
            "<form method='post'><input type='hidden' name='csrfmiddlewaretoken' value='{}'>"
            "<button name='decision' value='approve'>Allow</button> "
            "<button name='decision' value='deny'>Deny</button></form>",
            request.user, csrf_token,
        )
        response = HttpResponse(body)
        response["Cache-Control"] = "no-store"
        return response
    if request.POST.get("decision") != "approve":
        return _callback(values["redirect_uri"], {
            "error": "access_denied", "state": values["state"]
        })
    code = secrets.token_urlsafe(32)
    OAuthAuthorizationCode.objects.create(
        code_hash=hash_oauth_secret(code), user=request.user,
        client_id=values["client_id"], redirect_uri=values["redirect_uri"],
        resource=values["resource"], scope=MCP_SCOPE,
        code_challenge=values["code_challenge"],
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    return _callback(values["redirect_uri"], {"code": code, "state": values["state"]})


@router.register(re_path=r"^oauth/token$", route_type="api", url_name="oauth_token")
@csrf_exempt
def exchange_token(request: HttpRequest) -> HttpResponse:
    """Atomically exchange one authorization code for an MCP-only bearer token."""
    if not _enabled_or_404():
        return HttpResponse(status=404)
    if request.method != "POST":
        return HttpResponse(status=405)
    client_id = request.POST.get("client_id", "")
    redirect_uri = request.POST.get("redirect_uri", "")
    resource = request.POST.get("resource", "")
    verifier = request.POST.get("code_verifier", "")
    code = request.POST.get("code", "")
    if (
        request.POST.get("grant_type") != "authorization_code"
        or redirect_uri not in (_client_redirects(client_id) or [])
        or resource != oauth_resource(request)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
        or not code
    ):
        return _json_error("invalid_grant")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with transaction.atomic():
        authorization = OAuthAuthorizationCode.objects.select_for_update().filter(
            code_hash=hash_oauth_secret(code)
        ).first()
        if (
            authorization is None
            or authorization.expires_at <= timezone.now()
            or authorization.client_id != client_id
            or authorization.redirect_uri != redirect_uri
            or authorization.resource != resource
            or not secrets.compare_digest(authorization.code_challenge, challenge)
            or not authorization.user.is_active
        ):
            return _json_error("invalid_grant")
        user = authorization.user
        authorization.delete()
        token = TOKEN_PREFIX + secrets.token_urlsafe(48)
        expires_in = 12 * 60 * 60
        OAuthAccessToken.objects.create(
            token_hash=hash_oauth_secret(token), user=user, client_id=client_id,
            resource=resource, scope=MCP_SCOPE,
            expires_at=timezone.now() + timedelta(seconds=expires_in),
        )
    response = JsonResponse({
        "access_token": token, "token_type": "Bearer",
        "expires_in": expires_in, "scope": MCP_SCOPE,
    })
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response
