"""Scenario coverage for persistent shared agent tool configuration."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from bloomerp.agents.providers import AI_PROVIDER_REGISTRY
from bloomerp.agents.tool_access import allowed_internal_tools
from bloomerp.forms.agents.ai_agent import AIAgentDetailsForm
from bloomerp.models.agents import AIAgent, MCPIntegration
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)


class TestAIAgentTools(BloomerpModelTestCase):
    """Verify unrestricted defaults, explicit none, stable names and integration relations."""

    model = AIAgent

    def test_integration_selector_respects_row_sensitive_label_field_grants(
        self,
    ) -> None:
        """Show only permitted names and omit connection-mode and enabled labels without field grants."""
        user = get_user_model().objects.create_user(username="integration-name-viewer")
        content_type = ContentType.objects.get_for_model(MCPIntegration)
        for name in ("name", "connection_mode", "enabled"):
            ApplicationField.objects.get_or_create(
                content_type=content_type,
                field=name,
                defaults={"field_type": "CharField"},
            )
        policy = PolicyManager.create_policy(
            MCPIntegration,
            field_permissions={"name": "view"},
            row_permissions=[RowPolicyRuleContent(conditions=[], permissions=["view"])],
            global_permissions=["view"],
        )
        policy.assign_user(user)
        integration = MCPIntegration.objects.create(
            name="Visible name",
            endpoint_url="https://example.com/mcp",
            connection_mode="personal",
            enabled=False,
        )
        form = AIAgentDetailsForm(
            provider=AI_PROVIDER_REGISTRY.get("openai"), user=user
        )
        queryset = form.fields["mcp_integrations"].queryset
        self.assertEqual(list(queryset.values_list("pk", flat=True)), [integration.pk])
        label = form.fields["mcp_integrations"].label_from_instance(
            queryset.get(pk=integration.pk)
        )
        self.assertEqual(label, "Visible name")

    def test_inaccessible_integrations_cannot_be_selected_or_silently_removed(
        self,
    ) -> None:
        """Reject forged relation IDs while preserving existing hidden relations on valid edits."""
        user = get_user_model().objects.create_user(username="limited-tool-editor")
        agent = AIAgent.objects.create(**self.agent_args())
        agent.set_credentials({"api_key": "test-secret"})
        agent.internal_tools = ["unavailable_tool"]
        agent.save()
        integration = MCPIntegration.objects.create(
            name="Hidden", endpoint_url="https://example.com/mcp"
        )
        agent.mcp_integrations.add(integration)
        data = {
            "name": agent.name,
            "model_identifier": agent.model_identifier,
            "internal_tool_mode": "selected",
            "internal_tools": ["unavailable_tool"],
        }
        allowed = {
            "name",
            "model_identifier",
            "internal_tool_mode",
            "internal_tools",
            "mcp_integrations",
        }
        form = AIAgentDetailsForm(
            data={**data, "mcp_integrations": [str(integration.pk)]},
            instance=agent,
            provider=AI_PROVIDER_REGISTRY.get("openai"),
            user=user,
            allowed_fields=allowed,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("mcp_integrations", form.errors)
        form = AIAgentDetailsForm(
            data=data,
            instance=agent,
            provider=AI_PROVIDER_REGISTRY.get("openai"),
            user=user,
            allowed_fields=allowed,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(agent.mcp_integrations.all()), [integration])
        self.assertEqual(agent.internal_tools, ["unavailable_tool"])
        hidden_form = AIAgentDetailsForm(
            instance=agent,
            provider=AI_PROVIDER_REGISTRY.get("openai"),
            user=user,
            allowed_fields={"name", "model_identifier"},
        )
        self.assertNotIn("internal_tools", hidden_form.fields)
        self.assertNotIn("internal_tool_mode", hidden_form.fields)
        self.assertNotIn("mcp_integrations", hidden_form.fields)

    def agent_args(self) -> dict[str, Any]:
        """Provide the minimum valid provider configuration for lifecycle scenarios."""
        return {
            "name": "Tool settings agent",
            "provider": "openai",
            "model_identifier": "test",
        }

    def unrestricted(self, agent: AIAgent) -> bool:
        """Check that default agents retain access to the complete dynamic catalog."""
        return allowed_internal_tools(agent.pk) is None

    def no_tools(self, agent: AIAgent) -> bool:
        """Check that an explicit empty selection never falls back to all tools."""
        return allowed_internal_tools(agent.pk) == set()

    def stable_names(self, agent: AIAgent) -> bool:
        """Retain selected stable names even while their registered tools are unavailable."""
        return allowed_internal_tools(agent.pk) == {"extension_tool", "deleted_tool"}

    def attach_integrations(self, agent: AIAgent) -> None:
        """Select integration definitions in both modes without selecting credential records."""
        for mode in ("shared", "personal"):
            integration = MCPIntegration.objects.create(
                name=mode, endpoint_url="https://example.com/mcp", connection_mode=mode
            )
            agent.mcp_integrations.add(integration)

    def integrations_persist(self, agent: AIAgent) -> bool:
        """Read both configured definitions through the persisted many-to-many relation."""
        return set(
            agent.mcp_integrations.values_list("connection_mode", flat=True)
        ) == {"shared", "personal"}

    def get_test_scenarios(self) -> list[ModelScenario[AIAgent]]:
        """Describe meaningful configuration lifecycle outcomes and invalid list input."""
        return [
            ModelScenario(
                name="Default all becomes explicit none",
                create_args=self.agent_args,
                create_validators=self.unrestricted,
                update_args={"internal_tool_mode": "selected", "internal_tools": []},
                update_validators=self.no_tools,
            ),
            ModelScenario(
                name="Unavailable names and selected integrations persist",
                create_args={
                    **self.agent_args(),
                    "internal_tool_mode": "selected",
                    "internal_tools": ["extension_tool", "deleted_tool"],
                },
                post_create=self.attach_integrations,
                create_validators=[self.stable_names, self.integrations_persist],
            ),
            ModelScenario(
                name="Non-list tool configuration is rejected",
                create_args={**self.agent_args(), "internal_tools": {"tool": True}},
                expected_exceptions=[ExpectedModelException("create", ValidationError)],
            ),
        ]
