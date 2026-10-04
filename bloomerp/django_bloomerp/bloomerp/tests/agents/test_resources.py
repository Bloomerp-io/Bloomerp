"""Agent discovery, configuration and authenticated resource read coverage."""

import json
from typing import Any
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from bloomerp.agents.mcp import AgentApprovalRules, AgentMcpClient
from bloomerp.agents.providers import AI_PROVIDER_REGISTRY
from bloomerp.agents.resource_access import resource_tool_name
from bloomerp.agents.runtime import AgentRuntimeToolProposal
from bloomerp.forms.agents.ai_agent import AIAgentDetailsForm
from bloomerp.mcp.definition import McpResource, McpResourceTemplate
from bloomerp.models.agents import AIAgent
from bloomerp.router import BloomerpRouteRegistry, router
from bloomerp.tests.mcp.test_resources import denied_reader, guide_reader, node_reader

GUIDE_URI = "bloomerp://tests/guide"
TEMPLATE_URI = "bloomerp://tests/nodes/{subtype}"


@override_settings(ALLOWED_HOSTS=["erp.test"])
class AgentResourceTests(TestCase):
    """Exercise the resource bridge through the actual local MCP protocol."""

    def setUp(self) -> None:
        """Install isolated concrete and template resource readers and a configured actor."""
        self.user = get_user_model().objects.create_user(username="resource-actor")
        self.agent = AIAgent.objects.create(
            name="Resource agent", provider="openai", model_identifier="test"
        )
        self.client = AgentMcpClient(self.user.pk, "https://erp.test", self.agent.pk)
        registry = BloomerpRouteRegistry()
        registry.register(name="Guide", mcp=McpResource(uri=GUIDE_URI))(guide_reader)
        registry.register(
            name="Nodes", mcp=McpResourceTemplate(uri_template=TEMPLATE_URI)
        )(node_reader)
        registry.register(
            name="Private", mcp=McpResource(uri="bloomerp://tests/private")
        )(denied_reader)
        self.enterContext(
            patch.object(
                router, "get_mcp_resources", side_effect=registry.get_mcp_resources
            )
        )
        self.enterContext(
            patch.object(
                router,
                "get_mcp_resource_templates",
                side_effect=registry.get_mcp_resource_templates,
            )
        )

    def proposal(
        self, uri: str, arguments: dict[str, Any] | None = None
    ) -> AgentRuntimeToolProposal:
        """Construct the same versioned proposal used by runtime tool dispatch."""
        name = resource_tool_name(uri)
        definition = self.client.definition(self.client.catalog()[name])
        return AgentRuntimeToolProposal(
            provider_call_id="read-1",
            tool_identifier=name,
            tool_version=definition.version,
            arguments=arguments or {},
        )

    def test_default_catalog_and_read_preserve_identity(self) -> None:
        """Discover read-only guides and return content using the initiating user identity."""
        definition = self.client.catalog()[resource_tool_name(GUIDE_URI)]
        self.assertFalse(AgentApprovalRules().requires_approval(definition))
        result = self.client.dispatch(self.proposal(GUIDE_URI))
        self.assertIn(
            f"Guide for user {self.user.pk}", result["content"][0]["resource"]["text"]
        )
        self.assertEqual(result["content"][0]["resource"]["uri"], GUIDE_URI)

    def test_selected_resources_are_independent_of_tools_and_rechecked(self) -> None:
        """Permit selected guides with no ordinary tools, then reject reads after revocation."""
        self.agent.internal_tool_mode = "selected"
        self.agent.internal_resource_mode = "selected"
        self.agent.internal_resources = [GUIDE_URI, "bloomerp://tests/deleted"]
        self.agent.save()
        self.assertEqual(set(self.client.catalog()), {resource_tool_name(GUIDE_URI)})
        proposal = self.proposal(GUIDE_URI)
        self.agent.internal_resources = []
        self.agent.save()
        self.assertEqual(self.client.catalog(), {})
        with self.assertRaises(PermissionDenied):
            self.client.dispatch(proposal)
        with self.assertRaises(PermissionDenied):
            self.client.request("resources/read", {"uri": GUIDE_URI})
        with self.assertRaises(PermissionDenied):
            self.client.check_tool_access(self.agent.pk, proposal.tool_identifier)

    def test_templates_encode_arguments_and_reject_path_traversal(self) -> None:
        """Expand string parameters safely and preserve the protocol's template validation."""
        result = self.client.dispatch(
            self.proposal(TEMPLATE_URI, {"subtype": "Send email"})
        )
        self.assertEqual(
            json.loads(result["content"][0]["resource"]["text"])["subtype"],
            "Send email",
        )
        for value in ("..", "a/b", "a\\b"):
            with (
                self.subTest(value=value),
                self.assertRaises((ValueError, PermissionDenied)),
            ):
                self.client.dispatch(self.proposal(TEMPLATE_URI, {"subtype": value}))

    def test_reader_denial_and_inactive_actor_remain_enforced(self) -> None:
        """Agent resource selection cannot bypass the reader or caller authentication."""
        with self.assertRaises(ValidationError):
            self.client.dispatch(self.proposal("bloomerp://tests/private"))
        proposal = self.proposal(GUIDE_URI)
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            self.client.dispatch(proposal)

    def test_form_lists_resources_and_retains_unavailable_uris(self) -> None:
        """Render separate resource choices while respecting configuration field grants."""
        self.agent.internal_resources = ["bloomerp://tests/deleted"]
        form = AIAgentDetailsForm(
            instance=self.agent, provider=AI_PROVIDER_REGISTRY.get("openai")
        )
        choices = dict(form.fields["internal_resources"].choices)
        self.assertIn(GUIDE_URI, choices)
        self.assertIn(TEMPLATE_URI, choices)
        self.assertIn("Unavailable resource", choices["bloomerp://tests/deleted"])
        hidden = AIAgentDetailsForm(
            instance=self.agent,
            provider=AI_PROVIDER_REGISTRY.get("openai"),
            allowed_fields={"name"},
        )
        self.assertNotIn("internal_resources", hidden.fields)
        self.assertNotIn("internal_resource_mode", hidden.fields)

    def test_model_rejects_invalid_resource_configuration(self) -> None:
        """Keep resource selections as nonempty string identities rather than arbitrary JSON."""
        self.agent.internal_resources = {"uri": True}
        with self.assertRaises(ValidationError):
            self.agent.save()
