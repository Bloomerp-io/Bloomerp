"""Focused coverage for the optional MCP-only OAuth flow."""

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from bloomerp.config.definition import BloomerpAuthSettings, BloomerpConfig, OAuthSettings
from bloomerp.models.auth.oauth import OAuthAccessToken


@override_settings(BLOOMERP_CONFIG=BloomerpConfig(
    auth=BloomerpAuthSettings(oauth=OAuthSettings(enabled=True))
))
class McpOAuthTests(TestCase):
    """Exercise discovery, consent, PKCE, replay protection, and MCP isolation."""

    def setUp(self) -> None:
        """Create a normal Bloomerp user for the consent flow."""
        self.user = get_user_model().objects.create_user(
            username="mcp-oauth-user", password="test-password"
        )
        self.callback = "https://chatgpt.com/connector/oauth/demo-callback"
        self.resource = "http://testserver/mcp"
        self.verifier = "a" * 43
        self.challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.verifier.encode()).digest()
        ).rstrip(b"=").decode()

    def _register(self) -> str:
        """Register the fixed ChatGPT callback and return its public client ID."""
        response = self.client.post(
            reverse("oauth_register"),
            data=json.dumps({"redirect_uris": [self.callback], "token_endpoint_auth_method": "none"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["client_id"]

    def _authorization_url(self, client_id: str) -> str:
        """Build a complete S256 authorization-code request."""
        return reverse("oauth_authorize") + "?" + urlencode({
            "client_id": client_id,
            "redirect_uri": self.callback,
            "resource": self.resource,
            "scope": "mcp:tools",
            "response_type": "code",
            "state": "test-state",
            "code_challenge_method": "S256",
            "code_challenge": self.challenge,
        })

    def test_discovery_and_challenge(self) -> None:
        """Expose the catalog and prompt linking before an unauthenticated call."""
        metadata = self.client.get(reverse("oauth_resource_metadata"))
        self.assertEqual(metadata.json()["resource"], self.resource)
        server = self.client.get(reverse("oauth_server_metadata"))
        self.assertIn("S256", server.json()["code_challenge_methods_supported"])
        response = self.client.post(
            reverse("mcp"),
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        self.assertEqual(response.status_code, 200)
        catalog = self.client.post(
            reverse("mcp"),
            data=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(
            catalog.json()["result"]["tools"][0]["securitySchemes"],
            [{"type": "oauth2", "scopes": ["mcp:tools"]}],
        )
        challenge = self.client.post(
            reverse("mcp"),
            data=json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "test"}}),
            content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        self.assertIn("resource_metadata=", challenge.json()["result"]["_meta"]["mcp/www_authenticate"][0])

    def test_code_exchange_is_single_use_and_token_is_mcp_scoped(self) -> None:
        """Accept one PKCE exchange and authenticate the resulting MCP call."""
        client_id = self._register()
        self.client.force_login(self.user)
        url = self._authorization_url(client_id)
        self.assertEqual(self.client.get(url).status_code, 200)
        approved = self.client.post(url, {"decision": "approve"})
        self.assertEqual(approved.status_code, 302)
        code = parse_qs(urlsplit(approved["Location"]).query)["code"][0]
        self.assertEqual(parse_qs(urlsplit(approved["Location"]).query)["state"], ["test-state"])
        self.client.logout()
        exchange = {
            "grant_type": "authorization_code", "code": code,
            "client_id": client_id, "redirect_uri": self.callback,
            "resource": self.resource, "code_verifier": self.verifier,
        }
        bad_verifier = self.client.post(
            reverse("oauth_token"), {**exchange, "code_verifier": "b" * 43}
        )
        self.assertEqual(bad_verifier.status_code, 400)
        token_response = self.client.post(reverse("oauth_token"), exchange)
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["access_token"]
        self.assertEqual(self.client.post(reverse("oauth_token"), exchange).status_code, 400)
        message = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        authorized = self.client.post(
            reverse("mcp"), data=message, content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["result"]["serverInfo"]["name"], "Bloomerp")
        record = OAuthAccessToken.objects.get()
        record.resource = "https://another.example/mcp"
        record.save(update_fields=["resource"])
        rejected = self.client.post(
            reverse("mcp"), data=message, content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(rejected.status_code, 401)

    def test_rejects_unapproved_redirect(self) -> None:
        """Prevent public registration from becoming an open redirect."""
        response = self.client.post(
            reverse("oauth_register"),
            data=json.dumps({"redirect_uris": ["https://evil.example/callback"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
