"""Verify current-user discovery and authentication through the MCP transport."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, override_settings
from jsonschema import Draft202012Validator
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.mcp.view import McpEndpointView
from bloomerp.views.mcp.get_current_user import get_current_user


@override_settings(ALLOWED_HOSTS=["erp.test"])
class CurrentUserMcpTests(SimpleTestCase):
    """Exercise the registered tool without requiring database access or model grants."""

    def request_mcp(
        self, method: str, params: dict[str, Any], user: SimpleNamespace | AnonymousUser
    ) -> Response:
        """Send a JSON-RPC request as the supplied actor through the real MCP view."""
        request = APIRequestFactory().post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            format="json",
            secure=True,
            HTTP_HOST="erp.test",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        force_authenticate(request, user=user)
        return McpEndpointView.as_view()(request)

    def test_catalog_advertises_read_only_tool_without_arguments(self) -> None:
        """Publish the profile schema and reject caller-supplied identity arguments."""
        response = self.request_mcp(
            "tools/list", {}, SimpleNamespace(is_authenticated=True)
        )
        self.assertEqual(response.status_code, 200)
        tool = next(
            tool for tool in response.data["result"]["tools"]
            if tool["name"] == "get_current_user"
        )
        self.assertEqual(tool["title"], "GetCurrentUser")
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["annotations"]["openWorldHint"])
        validator = Draft202012Validator(tool["inputSchema"])
        self.assertTrue(validator.is_valid({}))
        self.assertFalse(validator.is_valid({"user_id": 2}))
        Draft202012Validator.check_schema(tool["outputSchema"])
        self.assertEqual(
            set(tool["outputSchema"]["required"]),
            {"id", "email", "first_name", "last_name", "username"},
        )

    def test_returns_only_each_callers_basic_profile(self) -> None:
        """Keep identities isolated and omit sensitive fields from the wire result."""
        for user_id in (1, 2):
            with self.subTest(user_id=user_id):
                expected = {
                    "id": user_id,
                    "email": f"user{user_id}@example.com",
                    "first_name": "Example",
                    "last_name": "User",
                    "username": f"user{user_id}",
                }
                user = SimpleNamespace(
                    **expected, pk=user_id, is_authenticated=True,
                    is_staff=False, is_superuser=False, password="private",
                )
                response = self.request_mcp(
                    "tools/call", {"name": "get_current_user", "arguments": {}}, user
                )
                self.assertEqual(response.status_code, 200)
                response.render()
                result = json.loads(response.content)["result"]
                self.assertNotIn("isError", result)
                self.assertEqual(result["structuredContent"], expected)
                self.assertEqual(json.loads(result["content"][0]["text"]), expected)

    def test_empty_optional_profile_values_are_preserved(self) -> None:
        """Return blank profile fields as strings rather than dropping their keys."""
        user = SimpleNamespace(
            pk=1, is_authenticated=True, email="", first_name="",
            last_name="", username="user1",
        )
        response = self.request_mcp(
            "tools/call", {"name": "get_current_user"}, user
        )
        self.assertEqual(response.data["result"]["structuredContent"], {
            "id": 1, "email": "", "first_name": "", "last_name": "",
            "username": "user1",
        })

    def test_anonymous_call_is_denied(self) -> None:
        """Require account authentication before any profile is returned."""
        for oauth_enabled in (False, True):
            with self.subTest(oauth_enabled=oauth_enabled), patch(
                "bloomerp.mcp.view.oauth_enabled", return_value=oauth_enabled
            ):
                response = self.request_mcp(
                    "tools/call", {"name": "get_current_user"}, AnonymousUser()
                )
                if oauth_enabled:
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.data["result"]["isError"])
                    self.assertNotIn("structuredContent", response.data["result"])
                else:
                    self.assertIn(response.status_code, (401, 403))

    def test_direct_view_rejects_anonymous_actor(self) -> None:
        """Keep the endpoint protected even when invoked outside the MCP transport."""
        request = APIRequestFactory().post("/mcp", {}, format="json")
        request.user = AnonymousUser()
        response = get_current_user(request)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 401)

    def test_identity_override_is_rejected(self) -> None:
        """Prevent arguments from selecting a different user's profile."""
        response = self.request_mcp(
            "tools/call",
            {"name": "get_current_user", "arguments": {"user_id": 2}},
            SimpleNamespace(is_authenticated=True),
        )
        self.assertTrue(response.data["result"]["isError"])
