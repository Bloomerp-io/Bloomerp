"""Verify MCP scenario dispatch, authentication, and fixture isolation."""

from typing import Any
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path

from bloomerp.mcp.definition import McpResource, McpResourceTemplate, McpTool
from bloomerp.mcp.view import McpEndpointView
from bloomerp.router import BloomerpRouteRegistry
from bloomerp.tests.base import (
    BloomerpMcpViewTestCase,
    ExpectedResult,
    McpRequestScenario,
)


def echo_tool(request: HttpRequest) -> dict[str, Any]:
    """Return the prepared arguments and the actor forwarded by MCP."""
    return {"value": request.data["value"], "user_id": request.user.pk}


def concrete_reader(request: HttpRequest) -> str:
    """Return a resource payload for an authenticated reader."""
    return "reference text"


def template_reader(request: HttpRequest, name: str) -> str:
    """Expose a decoded template parameter to verify URI encoding."""
    return name


def denied_reader(request: HttpRequest) -> str:
    """Raise an access denial to verify JSON-RPC resource errors."""
    raise PermissionDenied("Private reference")


urlpatterns = [path("mcp", McpEndpointView.as_view(), name="mcp")]


@override_settings(ROOT_URLCONF=__name__)
class McpViewTestCaseTests(BloomerpMcpViewTestCase):
    """Exercise the real HTTP transport using a temporary route registry."""

    view_name = "echo"

    def setUp(self) -> None:
        """Bind both registration checks and transport dispatch to test routes."""
        super().setUp()
        registry = BloomerpRouteRegistry()
        registry.register(
            url_name="echo",
            mcp=McpTool(
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                }
            ),
        )(echo_tool)
        registry.register(
            url_name="reference",
            mcp=McpResource(
                uri="bloomerp://test/reference",
            ),
        )(concrete_reader)
        registry.register(
            url_name="template",
            mcp=McpResourceTemplate(
                uri_template="bloomerp://test/{name}",
            ),
        )(template_reader)
        registry.register(
            url_name="denied",
            mcp=McpResource(
                uri="bloomerp://test/denied",
            ),
        )(denied_reader)
        for target, replacement in (
            ("bloomerp.tests.base.mcp_view_test_case.router", registry),
            ("bloomerp.mcp.view.router", registry),
            ("bloomerp.mcp.view.oauth_enabled", False),
        ):
            patcher = (
                patch(target, return_value=False)
                if replacement is False
                else patch(target, replacement)
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cleanups: list[str] = []

    def prepare_marker(self, scenario: McpRequestScenario) -> None:
        """Create scenario-only data and alter the tool argument before encoding."""
        get_user_model().objects.create(username="mcp-scenario-marker")
        scenario.arguments["value"] = "prepared"

    def record_cleanup(self, scenario: McpRequestScenario) -> None:
        """Record cleanup while scenario data is still available."""
        self.assertTrue(
            get_user_model().objects.filter(username="mcp-scenario-marker").exists()
        )
        self.cleanups.append("cleanup")

    def assert_rollback(self, scenario: McpRequestScenario) -> None:
        """Verify the preceding scenario's data and login cannot leak."""
        self.assertFalse(
            get_user_model().objects.filter(username="mcp-scenario-marker").exists()
        )
        self.assertEqual(self.cleanups, ["cleanup"])

    def get_test_scenarios(self) -> list[McpRequestScenario]:
        """Cover prepared tools, anonymous calls, resources, and protocol failures."""
        return [
            McpRequestScenario(
                name="Prepared arguments and authenticated actor reach the tool",
                user=self.normal_user,
                prepare=self.prepare_marker,
                cleanup=self.record_cleanup,
                expected=ExpectedResult(
                    response_validators=self.mcp_structured_content_equals(
                        {
                            "value": "prepared",
                            "user_id": self.normal_user.pk,
                        }
                    )
                ),
            ),
            McpRequestScenario(
                name="Anonymous scenario starts after rollback and logout",
                arguments={"value": "anonymous"},
                prepare=self.assert_rollback,
                expected=ExpectedResult(status_code=401),
            ),
            McpRequestScenario(
                name="Invalid tool arguments produce a tool error",
                user=self.normal_user,
                expected=ExpectedResult(response_validators=self.mcp_is_error()),
            ),
            McpRequestScenario(
                name="Concrete resource supplies its URI automatically",
                view_name="reference",
                user=self.normal_user,
                expected=ExpectedResult(
                    response_validators=self.mcp_resource_text_equals("reference text")
                ),
            ),
            McpRequestScenario(
                name="Resource template arguments are encoded and decoded",
                view_name="template",
                user=self.normal_user,
                arguments={"name": "some name?#"},
                expected=ExpectedResult(
                    response_validators=self.mcp_resource_text_equals("some name?#")
                ),
            ),
            McpRequestScenario(
                name="Explicit resource URI can exercise missing resources",
                view_name="reference",
                user=self.normal_user,
                uri="bloomerp://unregistered/missing",
                expected=ExpectedResult(response_validators=self.mcp_rpc_error(-32002)),
            ),
            McpRequestScenario(
                name="Denied resource reports a protocol error",
                view_name="denied",
                user=self.normal_user,
                expected=ExpectedResult(response_validators=self.mcp_rpc_error(-32001)),
            ),
        ]

    def test_resource_registration_checks(self) -> None:
        """Verify concrete and template registrations select their resource catalogs."""
        for view_name in ("reference", "template"):
            with self.subTest(view_name=view_name):
                self.view_name = view_name
                self.test_route_registration()

    def test_cleanup_and_rollback_after_validator_failure(self) -> None:
        """Release fixtures and authentication even when a response assertion fails."""
        scenario = McpRequestScenario(
            user=self.normal_user,
            prepare=self.prepare_marker,
            cleanup=self.record_cleanup,
            expected=ExpectedResult(response_validators=self.reject_response),
        )
        with self.assertRaisesRegex(AssertionError, "Response validator"):
            self._run_request_scenario(scenario, "intentional failure")
        self.assert_rollback(scenario)
        self.assertNotIn("_auth_user_id", self.client.session)

    def reject_response(self, response: HttpResponse) -> bool:
        """Force a failed assertion after a real MCP call."""
        return False
