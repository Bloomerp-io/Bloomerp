"""Request scenarios for the agent's usable tools configuration section."""

from django.http import HttpResponse
from django.urls import reverse

from bloomerp.agents.resource_access import internal_resource_choices
from bloomerp.agents.tool_access import internal_tool_choices
from bloomerp.models.agents import AIAgent, MCPIntegration
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestAIAgentToolsView(BloomerpDetailViewTestCase):
    """Exercise tool settings through the real permission-checked reconfigure wizard."""

    model = AIAgent
    view_name = "reconfigure"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create route context outside scenario savepoints so rollback preserves it."""
        super().setUp()
        self.test_object = self.create_test_object()

    def create_test_object(self) -> AIAgent:
        """Build one configured agent to supply detail-route context."""
        agent = AIAgent.objects.create(
            name="Configured tool agent", provider="openai", model_identifier="test"
        )
        agent.set_credentials({"api_key": "test-secret"})
        agent.save()
        return agent

    def prepare_details(self, scenario: RequestScenario) -> None:
        """Advance the wizard and select shared and personal integration definitions."""
        self.client.force_login(self.admin_user)
        self.client.post(
            reverse("ai_agents_detail_reconfigure", args=[self.get_test_object().pk]),
            {"provider": "openai"},
        )
        self.integrations = [
            MCPIntegration.objects.create(
                name=mode, endpoint_url="https://example.com/mcp", connection_mode=mode
            )
            for mode in ("shared", "personal")
        ]
        if scenario.method == "POST":
            scenario.data = {
                "name": "Configured tool agent",
                "model_identifier": "test",
                "request_timeout_seconds": 60,
                "internal_tool_mode": "selected",
                "internal_tools": [internal_tool_choices()[0][0]],
                "internal_resource_mode": "selected",
                "internal_resources": [internal_resource_choices()[0][0]],
                "mcp_integrations": [str(item.pk) for item in self.integrations],
            }

    def settings_visible(self, response: HttpResponse) -> bool:
        """Confirm complete selectors, labels, and the external connection requirements render."""
        self.assertContains(response, 'name="internal_tool_mode"')
        self.assertContains(response, 'name="internal_tools"')
        self.assertContains(response, 'name="internal_resource_mode"')
        self.assertContains(response, 'name="internal_resources"')
        for uri, label in internal_resource_choices():
            self.assertContains(response, uri)
        self.assertContains(response, 'name="mcp_integrations"')
        self.assertContains(
            response, "Missing or expired connections require reconnecting"
        )
        for integration in self.integrations:
            self.assertContains(response, str(integration.pk))
        return True

    def settings_persist(self, response: HttpResponse) -> bool:
        """Verify final submission saves both tool names and the integration relation."""
        agent = self.get_test_object()
        agent.refresh_from_db()
        self.assertEqual(agent.internal_tool_mode, "selected")
        self.assertEqual(agent.internal_tools, [internal_tool_choices()[0][0]])
        self.assertEqual(agent.internal_resource_mode, "selected")
        self.assertEqual(agent.internal_resources, [internal_resource_choices()[0][0]])
        self.assertEqual(set(agent.mcp_integrations.all()), set(self.integrations))
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Declare rendered settings, persistent selections, and denied ordinary-user access."""
        return [
            RequestScenario(
                name="Tools section renders both catalogs",
                user=self.admin_user,
                prepare=self.prepare_details,
                expected=ExpectedResult(response_validators=self.settings_visible),
            ),
            RequestScenario(
                name="Final submit persists internal and external selections",
                method="POST",
                user=self.admin_user,
                prepare=self.prepare_details,
                expected=ExpectedResult(
                    status_code=302, response_validators=self.settings_persist
                ),
            ),
            RequestScenario(
                name="Ordinary user cannot configure agent tools",
                user=self.normal_user,
                expected=ExpectedResult(status_code=403),
            ),
        ]
