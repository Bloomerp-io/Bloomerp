"""Exercise the routed two-step AI agent wizard and its secret boundary."""

from typing import Any

from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY
from bloomerp.forms.agents.ai_agent import AIAgentDetailsForm
from bloomerp.lookups import builtins as lookups
from bloomerp.models import ApplicationField
from bloomerp.models.agents import AIAgent, MCPIntegration
from bloomerp.permissions.definition import RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpModelViewTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.views.agents.create_ai_agent import CreateAIAgentView
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.urls import resolve, reverse


class CreateAIAgentViewTests(BloomerpModelViewTestCase):
    """Verify provider-specific creation, validation, permissions, and encrypted persistence."""

    model = AIAgent
    view_name = "add"
    auto_create_customers = False
    auto_create_users = False

    def extendedSetup(self) -> None:
        """Bind the real create route to an administrator and a denied staff account."""
        self.user = get_user_model().objects.create_user(
            username="wizard-admin", is_staff=True, is_superuser=True
        )
        self.denied = get_user_model().objects.create_user(
            username="wizard-denied", is_staff=True
        )
        self.client.force_login(self.user)
        self.url = reverse("ai_agents_add")

    def details(self, **overrides: Any) -> dict[str, Any]:
        """Build a structured final-step submission with independent run/response token limits."""
        return {
            "name": "Workspace assistant",
            "model_identifier": "custom-model",
            "enabled": "on",
            "request_timeout_seconds": 60,
            "max_tokens": 2000,
            "max_tool_calls": 12,
            "max_duration_seconds": 300,
            "credential__api_key": "wizard-secret",
            "parameter__temperature": "0.5",
            "parameter__max_tokens": "500",
            **overrides,
        }

    def select_provider(self, provider: str = "openai") -> None:
        """Complete the first step and assert the second and final step is shown."""
        response = self.client.post(self.url, {"provider": provider})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-wizard-step-index="1"')
        self.assertContains(response, 'data-wizard-total-steps="2"')

    def test_overrides_default_route_and_prevents_skipping_provider(self) -> None:
        """Resolve to the custom wizard and enforce its provider prerequisite server-side."""
        self.assertEqual(resolve(self.url).func.view_class, CreateAIAgentView)
        response = self.client.get(self.url + "?step=1")
        self.assertContains(response, 'data-wizard-step-index="0"')
        self.assertContains(response, "Anthropic Messages API")
        response = self.client.post(self.url, {"provider": "unknown"})
        self.assertContains(response, "Select an AI provider")
        self.assertEqual(AIAgent.objects.count(), 0)

    def test_creates_from_structured_inputs_without_session_or_response_secrets(
        self,
    ) -> None:
        """Encrypt only on final submission and persist typed settings and approvals."""
        self.select_provider()
        response = self.client.post(self.url, self.details(provider="anthropic"))
        self.assertEqual(response.status_code, 302)
        model = AIAgent.objects.get()
        self.assertEqual(model.provider, "openai")
        self.assertEqual(model.parameters, {"temperature": 0.5, "max_tokens": 500})
        self.assertEqual(model.max_tokens, 2000)
        self.assertNotIn(
            "approval_rules", {field.name for field in AIAgent._meta.fields}
        )
        self.assertEqual(
            model.validated_credentials().api_key.get_secret_value(), "wizard-secret"
        )
        self.assertNotIn("wizard-secret", str(model.credentials_encrypted))
        self.assertNotIn("wizard-secret", str(dict(self.client.session)))
        self.assertNotIn("ai_agent_create_wizard", self.client.session)

    def prepare_details_scenario(self, scenario: RequestScenario) -> None:
        """Select the provider through HTTP before one isolated final-step request."""
        self.client.force_login(self.user)
        self.select_provider()
        if scenario.name == "Invalid details redact credentials":
            scenario.data = self.details(parameter__temperature="9")
        else:
            self.integration = MCPIntegration.objects.create(
                name="Shared tools", endpoint_url="https://example.com/mcp"
            )
            scenario.data = self.details(
                internal_tool_mode="selected",
                mcp_integrations=[str(self.integration.pk)],
            )

    def invalid_details_redacted(self, response: HttpResponse) -> bool:
        """Keep nonsecret form inputs while rejecting invalid details without leaks."""
        self.assertContains(response, "Workspace assistant")
        self.assertNotContains(response, "wizard-secret")
        self.assertNotIn("wizard-secret", str(dict(self.client.session)))
        self.assertEqual(AIAgent.objects.count(), 0)
        return True

    def selected_tools_persist(self, response: HttpResponse) -> bool:
        """Persist an explicit empty internal allowlist and the selected integration."""
        agent = AIAgent.objects.get()
        self.assertEqual(agent.internal_tool_mode, "selected")
        self.assertEqual(agent.internal_tools, [])
        self.assertEqual(list(agent.mcp_integrations.all()), [self.integration])
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Describe final-step validation and tool selections on the registered create route."""
        return [
            RequestScenario(
                name="Invalid details redact credentials",
                method="POST",
                user=self.user,
                prepare=self.prepare_details_scenario,
                expected=ExpectedResult(
                    response_validators=self.invalid_details_redacted
                ),
            ),
            RequestScenario(
                name="Selected tools and integrations persist",
                method="POST",
                user=self.user,
                prepare=self.prepare_details_scenario,
                expected=ExpectedResult(
                    status_code=302, response_validators=self.selected_tools_persist
                ),
            ),
            RequestScenario(
                name="Ungranted creator is denied",
                user=self.denied,
                expected=ExpectedResult(status_code=403),
            ),
        ]

    def test_provider_specific_fields_and_back_navigation(self) -> None:
        """Generate supported inputs per provider and retain exactly two steps when going back."""
        self.select_provider("anthropic")
        response = self.client.get(self.url)
        self.assertContains(response, "credential__api_key")
        self.assertContains(response, 'data-row-columns="2"')
        self.assertContains(response, 'name="parameter__max_tokens" value="4096"')
        self.assertNotContains(response, 'name="approval_default"')
        self.assertNotContains(response, "parameter__seed")
        self.assertNotContains(response, "parameter__openai_reasoning_effort")
        response = self.client.post(
            self.url,
            {"_wizard_action": "back", "credential__api_key": "discard-secret"},
        )
        self.assertContains(response, 'data-wizard-step-index="0"')
        self.assertNotIn("discard-secret", str(dict(self.client.session)))
        self.select_provider("deepseek")
        self.assertEqual(self.client.post(self.url, self.details()).status_code, 302)

    def test_permissions_checked_again_on_final_submission(self) -> None:
        """Deny a viewer or a creator whose privileges were revoked during setup."""
        self.select_provider()
        self.user.is_superuser = False
        self.user.save()
        response = self.client.post(self.url, self.details())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AIAgent.objects.count(), 0)
        self.client.force_login(self.denied)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_endpoint_and_required_credential_validation(self) -> None:
        """Reject endpoints containing credentials and omit controls outside field grants."""
        provider = AI_PROVIDER_REGISTRY.get("openai")
        form = AIAgentDetailsForm(
            data=self.details(base_url="https://user:secret@example.com/v1"),
            provider=provider,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("base_url", form.errors)
        form = AIAgentDetailsForm(
            data=self.details(credential__api_key=""), provider=provider
        )
        self.assertFalse(form.is_valid())
        self.assertIn("credential__api_key", form.errors)
        form = AIAgentDetailsForm(
            provider=provider,
            allowed_fields={"name", "model_identifier", "credentials_encrypted"},
        )
        self.assertNotIn("approval_default", form.fields)
        self.assertNotIn("parameter__temperature", form.fields)
        self.assertNotIn("base_url", form.fields)

    def grant_creation(self, fields: set[str], provider: str = "openai") -> None:
        """Grant real row and field policies to the ordinary staff creator."""
        content_type = ContentType.objects.get_for_model(AIAgent)
        for name in fields | {"provider"}:
            ApplicationField.objects.get_or_create(
                content_type=content_type,
                field=name,
                defaults={"field_type": "CharField"},
            )
        policy = PolicyManager.create_policy(
            AIAgent,
            field_permissions=dict.fromkeys(fields, "add"),
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["add"],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="provider", operator=lookups.EQUALS.id, value=provider
                        )
                    ],
                )
            ],
            global_permissions=["add"],
        )
        PolicyManager.assign(policy, self.denied)
        self.client.force_login(self.denied)

    def test_row_and_field_policies_enforce_normal_user_creation(self) -> None:
        """Allow permitted rows and fields while rejecting forged denied fields and providers."""
        self.grant_creation(CreateAIAgentView.required_fields)
        self.select_provider()
        data = {
            "name": "Permitted model",
            "model_identifier": "custom-model",
            "credential__api_key": "wizard-secret",
        }
        self.assertEqual(
            self.client.post(
                self.url, {**data, "base_url": "https://example.com"}
            ).status_code,
            403,
        )
        self.assertEqual(AIAgent.objects.count(), 0)
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(AIAgent.objects.get().created_by, self.denied)
        self.select_provider("anthropic")
        self.assertEqual(
            self.client.post(self.url, {**data, "name": "Denied model"}).status_code,
            403,
        )
        self.assertEqual(AIAgent.objects.count(), 1)

    def test_row_specific_required_field_grants_are_enforced(self) -> None:
        """Reject creation when provider is granted globally but excluded on the selected row."""
        self.grant_creation(CreateAIAgentView.required_fields - {"provider"})
        self.grant_creation({"provider"}, provider="anthropic")
        self.select_provider()
        response = self.client.post(
            self.url,
            {
                "name": "Denied model",
                "model_identifier": "custom-model",
                "credential__api_key": "wizard-secret",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AIAgent.objects.count(), 0)

    def test_nonpositive_limits_have_field_errors_and_checkbox_stays_compact(
        self,
    ) -> None:
        """Show precise budget errors and render the enabled checkbox at its natural size."""
        from bs4 import BeautifulSoup

        self.select_provider()
        response = self.client.post(self.url, self.details(max_tool_calls="0"))
        self.assertContains(response, "Enter a value greater than zero")
        self.assertNotContains(response, "Invalid AI agent configuration")
        self.assertNotContains(response, "wizard-secret")
        self.assertEqual(AIAgent.objects.count(), 0)
        soup = BeautifulSoup(response.content, "html.parser")
        checkbox = soup.select_one('input[name="enabled"]')
        self.assertNotIn("w-full", checkbox.get("class", []))
        self.assertIn("w-4", checkbox.get("class", []))
        self.assertEqual(soup.select_one('input[name="max_tool_calls"]')["min"], "1")
        for name in ("request_timeout_seconds", "max_tokens", "max_duration_seconds"):
            form = AIAgentDetailsForm(
                data=self.details(**{name: "0"}),
                provider=AI_PROVIDER_REGISTRY.get("openai"),
            )
            self.assertFalse(form.is_valid())
            self.assertIn(name, form.errors)
        response = self.client.post(self.url, self.details(max_tool_calls=""))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(AIAgent.objects.get().max_tool_calls)
