"""Router and transport contracts for concrete and templated MCP resources."""

import base64
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import SimpleTestCase, override_settings
from django.views import View
from pydantic import ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from bloomerp.config.definition import BloomerpAuthSettings, BloomerpConfig, OAuthSettings
from bloomerp.mcp.definition import McpResource, McpResourceTemplate, McpTool
from bloomerp.mcp.view import McpEndpointView
from bloomerp.router import BloomerpRouteRegistry, RouteType, router


def guide_reader(request: HttpRequest) -> str:
    """Return a guide while exposing the forwarded request context for verification."""
    return f"Guide for user {request.user.pk} at {request.build_absolute_uri('/')} via {request.method}"


def node_reader(request: HttpRequest, subtype: str) -> dict[str, Any]:
    """Return one decoded node subtype as a JSON resource."""
    return {"subtype": subtype, "user_id": request.user.pk}


def binary_reader(request: HttpRequest) -> bytes:
    """Return binary bytes for the resource transport's base64 contract."""
    return b"\x00\xffbinary"


def denied_reader(request: HttpRequest) -> str:
    """Reject callers without exposing protected resource contents."""
    raise PermissionDenied("Private guide")


class ClassResourceReader(View):
    """Verify plain Django class readers receive authentication and URI arguments."""

    def get(self, request: HttpRequest, subtype: str) -> HttpResponse:
        """Return the resolved argument under the forwarded caller's identity."""
        return HttpResponse(f"{request.user.pk}:{subtype}")


class McpResourceRegistrationTests(SimpleTestCase):
    """Keep resource registration compatible with existing tools and URL patterns."""

    def test_infers_resource_type_and_separates_tools_and_http_routes(self) -> None:
        """Register distinct pathless resources without leaking them into tool/HTTP catalogs."""
        registry = BloomerpRouteRegistry()
        registry.register(name="Example", mcp=McpTool())(guide_reader)
        registry.register(name="Example", mcp=McpResource(uri="bloomerp://guides/z"))(guide_reader)
        registry.register(name="Example", mcp=McpResource(uri="bloomerp://guides/a"))(guide_reader)
        registry.register(name="Nodes", mcp=McpResourceTemplate(
            uri_template="bloomerp://nodes/{subtype}",
        ))(node_reader)
        self.assertEqual(len(registry.get_mcp_routes()), 1)
        self.assertEqual(
            [route.mcp.uri for route in registry.get_mcp_resources()],
            ["bloomerp://guides/a", "bloomerp://guides/z"],
        )
        self.assertEqual(len(registry.get_mcp_resource_templates()), 1)
        self.assertEqual(registry.create_url_patterns(), [])
        self.assertEqual(registry.create_websocket_url_patterns(), [])
        resource = registry.get_mcp_resources()[0]
        self.assertEqual(resource.route_type, RouteType.MCP_RESOURCE)
        self.assertFalse(resource.searchable)
        self.assertIsNone(resource.mcp_tool_name)
        self.assertEqual(len(registry.filter(route_type="mcp_resource")), 3)
        with self.assertRaisesRegex(ValueError, "do not have Django URL patterns"):
            registry.build_url_pattern(resource)

    def test_explicit_resource_registration_and_uri_override(self) -> None:
        """Use URI identity rather than display names or empty paths for overrides."""
        registry = BloomerpRouteRegistry()
        contract = McpResource(uri="bloomerp://guides/policy")
        registry.register(name="First", route_type="mcp_resource", mcp=contract)(guide_reader)
        with self.assertRaisesRegex(ValueError, "Duplicate MCP resource URI"):
            registry.register(name="Duplicate", mcp=contract)(guide_reader)
        registry.register(name="Replacement", mcp=contract, override=True)(guide_reader)
        self.assertEqual(len(registry.routes), 1)
        self.assertEqual(registry.routes[0].name, "Replacement")

    def test_rejects_equivalent_templates_and_prefers_concrete_uris(self) -> None:
        """Reject renamed duplicate patterns while letting concrete documents override lookup."""
        registry = BloomerpRouteRegistry()
        registry.register(mcp=McpResourceTemplate(uri_template="bloomerp://nodes/{subtype}"))(node_reader)
        with self.assertRaisesRegex(ValueError, "Duplicate MCP resource URI"):
            registry.register(mcp=McpResourceTemplate(uri_template="bloomerp://nodes/{name}"))(node_reader)
        registry.register(mcp=McpResource(uri="bloomerp://nodes/SEND_EMAIL"))(guide_reader)
        route, arguments = registry.resolve_mcp_resource("bloomerp://nodes/SEND_EMAIL")
        self.assertIsInstance(route.mcp, McpResource)
        self.assertEqual(arguments, {})

    def test_rejects_invalid_route_contract_combinations(self) -> None:
        """Prevent resource contracts from acquiring HTTP routes or tool execution semantics."""
        contract = McpResource(uri="bloomerp://guides/policy")
        for options in (
            {"path": "guide/"}, {"re_path": "^guide/$"}, {"route_type": "api"},
            {"route_type": "mcp"}, {"models": "__all__"}, {"searchable": True},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                BloomerpRouteRegistry().register(mcp=contract, **options)(guide_reader)
        with self.assertRaises(ValueError):
            BloomerpRouteRegistry().register(route_type="mcp_resource", mcp=McpTool())(guide_reader)
        with self.assertRaises(ValueError):
            BloomerpRouteRegistry().register(route_type="mcp_resource")(guide_reader)

    def test_validates_resource_addresses_and_supported_template_syntax(self) -> None:
        """Reject malformed URIs, unsupported RFC expressions, and reserved reader arguments."""
        for uri in ("relative/path", "bloomerp://bad path", "bloomerp://bad/%GG", "bloomerp://{name}"):
            with self.subTest(uri=uri), self.assertRaises(ValidationError):
                McpResource(uri=uri)
        for template in ("bloomerp://nodes/{+path}", "bloomerp://nodes/{x}/{x}",
                         "bloomerp://nodes/{request}", "{scheme}://nodes/{x}", "bloomerp://nodes"):
            with self.subTest(template=template), self.assertRaises(ValidationError):
                McpResourceTemplate(uri_template=template)


@override_settings(
    ALLOWED_HOSTS=["erp.test"],
    BLOOMERP_CONFIG=BloomerpConfig(auth=BloomerpAuthSettings(oauth=OAuthSettings(enabled=True))),
)
class McpResourceTransportTests(SimpleTestCase):
    """Exercise discovery and authenticated resource reading through JSON-RPC."""

    def setUp(self) -> None:
        """Supply isolated catalogs while exercising the production URI resolver."""
        self.registry = BloomerpRouteRegistry()
        self.registry.register(
            name="Policy guide", description="Create policies", mcp=McpResource(
                uri="bloomerp://guides/policy", mime_type="text/markdown",
            ),
        )(guide_reader)
        self.registry.register(name="Node reference", mcp=McpResourceTemplate(
            uri_template="bloomerp://nodes/{subtype}", mime_type="application/json",
            parameter_schema={"type": "object", "properties": {
                "subtype": {"type": "string", "enum": ["SEND_EMAIL", "CUSTOM NODE"]},
            }, "required": ["subtype"], "additionalProperties": False},
        ))(node_reader)
        self.registry.register(name="Binary", mcp=McpResource(
            uri="bloomerp://binary", mime_type="application/octet-stream",
        ))(binary_reader)
        self.registry.register(name="Private", mcp=McpResource(uri="bloomerp://private"))(denied_reader)
        self.registry.register(name="Class reader", mcp=McpResourceTemplate(
            uri_template="bloomerp://class/{subtype}",
        ))(ClassResourceReader)
        for name in ("get_mcp_resources", "get_mcp_resource_templates", "resolve_mcp_resource", "get_mcp_routes"):
            self.enterContext(patch.object(router, name, getattr(self.registry, name)))

    def rpc(self, method: str, params: dict[str, Any] | None = None, authenticated: bool = True) -> Any:
        """Send MCP JSON-RPC with an optional authenticated linked account."""
        request = APIRequestFactory().post(
            "/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            format="json", secure=True, HTTP_HOST="erp.test",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        if authenticated:
            force_authenticate(request, user=SimpleNamespace(pk=42, is_authenticated=True))
        return McpEndpointView.as_view()(request)

    def test_advertises_resources_and_lists_metadata_without_reading_contents(self) -> None:
        """Expose capabilities and separate resource/template catalogs before account linking."""
        initialized = self.rpc("initialize", authenticated=False)
        self.assertEqual(initialized.data["result"]["capabilities"]["resources"], {})
        catalog = self.rpc("resources/list", authenticated=False).data["result"]["resources"]
        guide = next(resource for resource in catalog if resource["uri"] == "bloomerp://guides/policy")
        self.assertEqual(guide["mimeType"], "text/markdown")
        self.assertEqual(guide["description"], "Create policies")
        self.assertNotIn("text", guide)
        templates = self.rpc("resources/templates/list").data["result"]["resourceTemplates"]
        self.assertEqual(len(templates), 2)
        self.assertEqual(self.rpc("tools/list").data["result"]["tools"], [])

    def test_reads_text_json_and_binary_resources_with_caller_context(self) -> None:
        """Preserve user/origin identity and serialize each resource content representation."""
        guide = self.rpc("resources/read", {"uri": "bloomerp://guides/policy"}).data["result"]["contents"][0]
        self.assertEqual(guide["text"], "Guide for user 42 at https://erp.test/ via GET")
        node = self.rpc("resources/read", {"uri": "bloomerp://nodes/CUSTOM%20NODE"}).data["result"]["contents"][0]
        self.assertEqual(json.loads(node["text"]), {"subtype": "CUSTOM NODE", "user_id": 42})
        binary = self.rpc("resources/read", {"uri": "bloomerp://binary"}).data["result"]["contents"][0]
        self.assertEqual(base64.b64decode(binary["blob"]), b"\x00\xffbinary")
        class_result = self.rpc("resources/read", {"uri": "bloomerp://class/SEND_EMAIL"}).data["result"]["contents"][0]
        self.assertEqual(class_result["text"], "42:SEND_EMAIL")

    def test_requires_authentication_and_respects_reader_permissions(self) -> None:
        """Challenge anonymous reads and convert reader permission failures to protocol errors."""
        denied = self.rpc("resources/read", {"uri": "bloomerp://guides/policy"}, authenticated=False)
        self.assertEqual(denied.status_code, 401)
        self.assertIn("resource_metadata", denied["WWW-Authenticate"])
        self.assertEqual(self.rpc("resources/read", {"uri": "bloomerp://private"}).data["error"]["code"], -32001)

    def test_rejects_unknown_malformed_and_invalid_parameter_uris(self) -> None:
        """Resolve only registered resources and validate decoded template arguments."""
        for uri, expected_code in (
            ("bloomerp://unknown", -32002), ("relative/path", -32602),
            ("bloomerp://nodes/UNKNOWN", -32602), ("bloomerp://nodes/%2Fetc", -32602),
            ("bloomerp://nodes/..", -32602), ("bloomerp://nodes/%00", -32602),
        ):
            with self.subTest(uri=uri):
                self.assertEqual(self.rpc("resources/read", {"uri": uri}).data["error"]["code"], expected_code)
        self.assertEqual(self.rpc("resources/read", {"uri": 1}).data["error"]["code"], -32602)

    def test_reports_ambiguous_template_matches_without_running_a_reader(self) -> None:
        """Reject overlapping templates rather than silently selecting a handler."""
        self.registry.register(mcp=McpResourceTemplate(uri_template="bloomerp://class/{subtype}x"))(node_reader)
        response = self.rpc("resources/read", {"uri": "bloomerp://class/ax"})
        self.assertEqual(response.data["error"]["code"], -32602)
