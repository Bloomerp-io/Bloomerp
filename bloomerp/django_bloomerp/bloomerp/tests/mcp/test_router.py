from django.http import HttpResponse
from django.test import SimpleTestCase

from bloomerp.mcp.definition import McpTool
from bloomerp.router import BloomerpRouteRegistry


def api_view(_request):
    return HttpResponse("ok")


class McpRouterTests(SimpleTestCase):
    def test_registers_mcp_metadata_on_api_route(self):
        registry = BloomerpRouteRegistry()
        tool = McpTool(title="Example")

        registry.register(
            path="example/",
            route_type="api",
            name="Example",
            url_name="example.tool",
            mcp=tool,
        )(api_view)

        route = registry.routes[0]
        self.assertIs(route.mcp, tool)
        self.assertEqual(route.mcp_tool_name, "example.tool")

    def test_get_mcp_routes_excludes_regular_routes_and_sorts_by_name(self):
        registry = BloomerpRouteRegistry()
        registry.register(
            path="zulu/",
            route_type="api",
            name="Zulu",
            url_name="zulu",
            mcp=McpTool(),
        )(api_view)
        registry.register(
            path="regular/",
            route_type="api",
            name="Regular",
            url_name="regular",
        )(api_view)
        registry.register(
            path="alpha/",
            route_type="api",
            name="Alpha",
            url_name="alpha",
            mcp=McpTool(),
        )(api_view)

        self.assertEqual(
            [route.mcp_tool_name for route in registry.get_mcp_routes()],
            ["alpha", "zulu"],
        )

    def test_rejects_mcp_on_non_api_route(self):
        registry = BloomerpRouteRegistry()

        with self.assertRaisesRegex(ValueError, "only be attached to API routes"):
            registry.register(
                path="example/",
                route_type="app",
                name="Example",
                url_name="example",
                mcp=McpTool(),
            )(api_view)

    def test_rejects_invalid_mcp_tool_name(self):
        registry = BloomerpRouteRegistry()

        with self.assertRaisesRegex(ValueError, "MCP tool names must be"):
            registry.register(
                path="example/",
                route_type="api",
                name="Example",
                url_name="invalid/name",
                mcp=McpTool(),
            )(api_view)

    def test_rejects_duplicate_mcp_tool_name(self):
        registry = BloomerpRouteRegistry()
        registration = {
            "route_type": "api",
            "name": "Example",
            "url_name": "duplicate",
            "mcp": McpTool(),
        }
        registry.register(path="first/", **registration)(api_view)

        with self.assertRaisesRegex(ValueError, "Duplicate MCP tool name: duplicate"):
            registry.register(path="second/", **registration)(api_view)

    def test_override_can_replace_same_mcp_route(self):
        registry = BloomerpRouteRegistry()
        registry.register(
            path="example/",
            route_type="api",
            name="Example",
            url_name="example",
            mcp=McpTool(title="First"),
        )(api_view)

        registry.register(
            path="example/",
            route_type="api",
            name="Example",
            url_name="example",
            override=True,
            mcp=McpTool(title="Replacement"),
        )(api_view)

        self.assertEqual(len(registry.routes), 1)
        self.assertEqual(registry.routes[0].mcp.title, "Replacement")
