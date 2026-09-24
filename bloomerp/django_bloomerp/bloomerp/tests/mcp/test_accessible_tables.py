"""MCP transport coverage for the accessible SQL tables view."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from bloomerp.config.definition import BloomerpAuthSettings, BloomerpConfig, OAuthSettings
from bloomerp.services.sql_services import DatabaseTable, Field


@override_settings(BLOOMERP_CONFIG=BloomerpConfig(
    auth=BloomerpAuthSettings(oauth=OAuthSettings(enabled=True))
))
class AccessibleTablesMcpTests(TestCase):
    """Ensure MCP uses the view's authenticated GET and serializer contract."""

    def _call_tool(self, arguments: dict[str, object]) -> dict[str, object]:
        """Send one accessible-tables tool call through the MCP transport."""
        response = self.client.post(
            reverse("mcp"),
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "api_sql_accessible_tables",
                    "arguments": arguments,
                },
            }),
            content_type="application/json",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["result"]

    def test_requires_authentication_before_listing_tables(self) -> None:
        """Do not call the SQL service for an anonymous MCP request."""
        with patch(
            "bloomerp.views.api.sql.accessible_tables.SqlExecutor.get_accessible_tables_and_fields"
        ) as tables_method:
            result = self._call_tool({})

        self.assertTrue(result["isError"])
        self.assertIn("mcp/www_authenticate", result["_meta"])
        tables_method.assert_not_called()

    def test_forwards_arguments_to_the_permission_aware_view(self) -> None:
        """Pass search and pagination to the existing view for a signed-in user."""
        user = get_user_model().objects.create_user(
            username="accessible-tables-mcp-user", password="test-password"
        )
        self.client.force_login(user)
        available = [
            DatabaseTable(
                name="customers",
                fields=[
                    Field(name="name", field_type="text"),
                    Field(name="email", field_type="text"),
                ],
            ),
            DatabaseTable(
                name="invoices",
                fields=[Field(name="amount", field_type="integer")],
            ),
        ]
        with patch(
            "bloomerp.views.api.sql.accessible_tables.SqlExecutor.get_accessible_tables_and_fields",
            return_value=available,
        ) as tables_method:
            result = self._call_tool({
                "search": "EMAIL", "page": 1, "page_size": 1, "refresh": True
            })

        tables_method.assert_called_once_with()
        self.assertNotIn("isError", result)
        payload = result["structuredContent"]
        self.assertEqual(payload["total_tables"], 1)
        self.assertEqual(payload["page_size"], 1)
        self.assertTrue(payload["refreshed"])
        self.assertEqual(payload["databases"][0]["tables"][0]["name"], "customers")
        self.assertEqual(
            [field["name"] for field in payload["databases"][0]["tables"][0]["fields"]],
            ["email"],
        )

    def test_rejects_arguments_outside_serializer_schema(self) -> None:
        """Reject invalid pagination before the underlying view executes."""
        user = get_user_model().objects.create_user(
            username="accessible-tables-schema-user", password="test-password"
        )
        self.client.force_login(user)
        with patch(
            "bloomerp.views.api.sql.accessible_tables.SqlExecutor.get_accessible_tables_and_fields"
        ) as tables_method:
            result = self._call_tool({"page_size": 101})

        self.assertTrue(result["isError"])
        tables_method.assert_not_called()
