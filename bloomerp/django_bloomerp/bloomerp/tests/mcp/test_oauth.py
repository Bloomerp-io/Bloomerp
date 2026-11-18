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
from bloomerp.tests.base import BloomerpAPIViewTestCase, ExpectedResult, RequestScenario


@override_settings(BLOOMERP_CONFIG=BloomerpConfig(
    auth=BloomerpAuthSettings(oauth=OAuthSettings(enabled=True))
))
class McpOAuthTests(TestCase):
    """Exercise discovery, consent, PKCE, replay protection, and MCP isolation."""

    def setUp(self) -> None:
        """Create a normal Bloomerp user for the consent flow."""
        self.user = get_user_model().objects.create_user(
            username="mcp-oauth-user", password="test-password", is_staff=True,
        )
        self.resource = "http://testserver/mcp"
        self.verifier = "a" * 43
        self.challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.verifier.encode()).digest()
        ).rstrip(b"=").decode()

    def _register(self, callback: str) -> str:
        """Register the callback and verify the public client metadata."""
        response = self.client.post(
            reverse("oauth_register"),
            data=json.dumps({"redirect_uris": [callback], "token_endpoint_auth_method": "none"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        client = response.json()
        self.assertEqual(client["redirect_uris"], [callback])
        self.assertEqual(client["token_endpoint_auth_method"], "none")
        return client["client_id"]

    def _authorization_url(self, client_id: str, callback: str) -> str:
        """Build a complete S256 authorization-code request."""
        return reverse("oauth_authorize") + "?" + urlencode({
            "client_id": client_id,
            "redirect_uri": callback,
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
        """Complete the same OAuth and MCP flow with different client providers."""
        for callback in (
            "https://chatgpt.com/connector/oauth/demo-callback",
            "https://claude.ai/api/mcp/auth_callback",
            "https://connector.example/oauth/callback",
        ):
            with self.subTest(callback=callback):
                self._assert_oauth_round_trip(callback)

    def _assert_oauth_round_trip(self, callback: str) -> None:
        """Accept one PKCE exchange and execute a tool as the linked staff user."""
        client_id = self._register(callback)
        self.client.force_login(self.user)
        url = self._authorization_url(client_id, callback)
        self.assertContains(self.client.get(url), urlsplit(callback).netloc)
        wrong_url = self._authorization_url(client_id, callback + "/unregistered")
        self.assertEqual(self.client.get(wrong_url).status_code, 400)
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        approved = self.client.post(url, {"decision": "approve"})
        self.assertEqual(approved.status_code, 302)
        location = urlsplit(approved["Location"])
        self.assertEqual(location._replace(query="").geturl(), callback)
        callback_params = parse_qs(location.query)
        self.assertEqual(callback_params["state"], ["test-state"])
        self.client.logout()
        exchange = {
            "grant_type": "authorization_code", "code": callback_params["code"][0],
            "client_id": client_id, "redirect_uri": callback,
            "resource": self.resource, "code_verifier": self.verifier,
        }
        bad_verifier = self.client.post(
            reverse("oauth_token"), {**exchange, "code_verifier": "b" * 43}
        )
        self.assertEqual(bad_verifier.status_code, 400)
        bad_redirect = self.client.post(
            reverse("oauth_token"), {**exchange, "redirect_uri": callback + "/unregistered"}
        )
        self.assertEqual(bad_redirect.status_code, 400)
        token_response = self.client.post(reverse("oauth_token"), exchange)
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["access_token"]
        self.assertEqual(self.client.post(reverse("oauth_token"), exchange).status_code, 400)
        message = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "get_current_user"},
        })
        authorized = self.client.post(
            reverse("mcp"), data=message, content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(authorized.status_code, 200)
        profile = authorized.json()["result"]["structuredContent"]
        self.assertEqual(str(profile["id"]), str(self.user.pk))
        self.assertEqual(profile["username"], self.user.username)
        record = OAuthAccessToken.objects.get(client_id=client_id)
        record.resource = "https://another.example/mcp"
        record.save(update_fields=["resource"])
        rejected = self.client.post(
            reverse("mcp"), data=message, content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(rejected.status_code, 401)


@override_settings(BLOOMERP_CONFIG=BloomerpConfig(
    auth=BloomerpAuthSettings(oauth=OAuthSettings(enabled=True))
))
class TestOAuthRegisterView(BloomerpAPIViewTestCase):
    """Validate callback URLs at dynamic client registration."""

    view_name = "oauth_register"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise malformed or unsupported callback URLs at the public endpoint."""
        return [
            RequestScenario(
                name=f"Rejects {name}",
                method="POST",
                data={"redirect_uris": [callback]},
                content_type="application/json",
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=self.json_key_equals("error", "invalid_client_metadata"),
                ),
            )
            for name, callback in (
                ("an HTTP URL", "http://connector.example/callback"),
                ("a relative URL", "/callback"),
                ("embedded credentials", "https://user@connector.example/callback"),
                ("a malformed host", "https://[invalid/callback"),
                ("an invalid port", "https://connector.example:99999/callback"),
                ("a fragment", "https://connector.example/callback#fragment"),
            )
        ]
