"""Declarative MCP scenarios using the shared HTTP request lifecycle."""

from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from bloomerp.mcp.definition import McpResource, McpResourceTemplate, McpTool
from bloomerp.router import BloomerpRoute, router
from bloomerp.tests.base.request_test_case_mixin import (
    RequestScenario,
    RequestTestCaseMixin,
    ResponseValidator,
)
from bloomerp.tests.utils.users import create_admin, create_normal_user


@dataclass
class McpRequestScenario(RequestScenario):
    """Call a registered tool or read a resource with optional template arguments."""

    method: Literal["POST"] = "POST"
    arguments: dict[str, Any] = field(default_factory=dict)
    uri: str | None = None


class BloomerpMcpViewTestCase(RequestTestCaseMixin, TestCase):
    """Test MCP tools and resource readers through the authenticated HTTP transport."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Provide standard actors without creating unrelated dynamic models."""
        super().setUpTestData()
        cls.admin_user = create_admin()
        cls.normal_user = create_normal_user()

    def get_test_scenarios(self) -> list[McpRequestScenario]:
        """Return the concrete endpoint's MCP call and resource-read scenarios."""
        raise NotImplementedError("MCP test cases must define request scenarios")

    def get_route(self, view_name: str | None = None) -> BloomerpRoute:
        """Require exactly one MCP registration with the selected route name."""
        selected_name = view_name or self.view_name
        routes = [
            route
            for route in router.get_routes()
            if route.url_name == selected_name and route.mcp is not None
        ]
        self.assertEqual(
            len(routes), 1, f"Expected one MCP route named {selected_name!r}"
        )
        return routes[0]

    def test_route_registration(self) -> None:
        """Verify the endpoint is advertised in the appropriate MCP catalog."""
        if self.view_name is None:
            return
        route = self.get_route()
        if isinstance(route.mcp, McpTool):
            catalog = router.get_mcp_routes()
        elif isinstance(route.mcp, McpResourceTemplate):
            catalog = router.get_mcp_resource_templates()
        else:
            catalog = router.get_mcp_resources()
        self.assertIn(route, catalog)

    def _get_request_kwargs(
        self, setup: RequestScenario, view_name: str
    ) -> dict[str, Any]:
        """Encode prepared scenario arguments in the registered endpoint's MCP request."""
        if not isinstance(setup, McpRequestScenario):
            raise TypeError("MCP views require McpRequestScenario")
        if setup.method != "POST":
            raise ValueError("MCP transport requests must use POST")
        route = self.get_route(view_name)
        contract = route.mcp
        if isinstance(contract, McpTool):
            method = "tools/call"
            params = {"name": route.mcp_tool_name, "arguments": setup.arguments}
        else:
            method = "resources/read"
            uri = setup.uri
            if uri is None:
                if isinstance(contract, McpResourceTemplate):
                    uri = contract.uri_template.format(
                        **{
                            name: quote(str(value), safe="")
                            for name, value in setup.arguments.items()
                        }
                    )
                else:
                    assert isinstance(contract, McpResource)
                    uri = contract.uri
            params = {"uri": uri}
        return {
            "path": reverse("mcp"),
            "data": {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            "content_type": "application/json",
            "headers": {
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
                **(setup.headers or {}),
            },
            "follow": setup.follow,
        }

    @classmethod
    def mcp_is_error(cls, expected: bool = True) -> ResponseValidator:
        """Validate an MCP tool error flag, treating an omitted flag as success."""

        def validator(response: HttpResponse) -> bool:
            """Check the tool outcome without mistaking a JSON-RPC error for success."""
            payload = response.json()
            result = payload.get("result")
            return isinstance(result, dict) and result.get("isError", False) is expected

        return cls._named_validator(f"mcp_is_error({expected!r})", validator)

    @classmethod
    def mcp_structured_content_equals(
        cls, expected: dict[str, Any]
    ) -> ResponseValidator:
        """Validate the structured payload returned by a successful MCP tool."""

        def validator(response: HttpResponse) -> bool:
            """Compare the tool payload only when the MCP call succeeded."""
            result = response.json().get("result", {})
            return (
                not result.get("isError")
                and result.get("structuredContent") == expected
            )

        return cls._named_validator("mcp_structured_content_equals()", validator)

    @classmethod
    def mcp_rpc_error(cls, code: int) -> ResponseValidator:
        """Validate a JSON-RPC error such as denied or missing resource access."""

        def validator(response: HttpResponse) -> bool:
            """Check the protocol error code outside the tool-result envelope."""
            return response.json().get("error", {}).get("code") == code

        return cls._named_validator(f"mcp_rpc_error({code})", validator)

    @classmethod
    def mcp_resource_text_equals(cls, expected: str) -> ResponseValidator:
        """Validate the text returned by a successful resource read."""

        def validator(response: HttpResponse) -> bool:
            """Require one resource content entry with the expected text."""
            contents = response.json().get("result", {}).get("contents", [])
            return len(contents) == 1 and contents[0].get("text") == expected

        return cls._named_validator("mcp_resource_text_equals()", validator)
