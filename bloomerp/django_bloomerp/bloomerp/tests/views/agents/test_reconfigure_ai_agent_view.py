"""Verify detail-tab reconfiguration preserves settings, identity, and encrypted secrets."""

from typing import Any

from bloomerp.models import ApplicationField
from bloomerp.models.agents import AIAgent, AIAgentAccess
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.views.agents.create_ai_agent import CreateAIAgentView
from bloomerp.views.agents.reconfigure_ai_agent import ReconfigureAIAgentView
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.urls import resolve, reverse


class ReconfigureAIAgentViewTests(BloomerpDetailViewTestCase):
    """Exercise real routes and posted forms rather than bypassing wizard state."""

    model = AIAgent
    view_name = "reconfigure"
    auto_create_customers = False
    auto_create_users = False

    def extendedSetup(self) -> None:
        """Create a configured agent and log in as a configuration administrator."""
        self.user = get_user_model().objects.create_user(
            username="reconfigure-admin", is_staff=True, is_superuser=True
        )
        self.other = get_user_model().objects.create_user(
            username="reconfigure-user", is_staff=True
        )
        self.agent = AIAgent.objects.create(
            name="Existing assistant",
            provider="openai",
            model_identifier="existing-model",
            default_instructions="Keep these instructions",
            base_url="https://example.com/v1",
            parameters={
                "temperature": 0.4,
                "stop_sequences": ["halt"],
                "parallel_tool_calls": True,
            },
            max_tokens=1234,
            max_tool_calls=7,
            max_duration_seconds=120,
            request_timeout_seconds=45,
            created_by=self.user,
        )
        self.agent.set_credentials({"api_key": "existing-secret"})
        self.agent.save()
        self.url = reverse("ai_agents_detail_reconfigure", args=[self.agent.pk])
        self.client.force_login(self.user)

    def details(self, **overrides: Any) -> dict[str, Any]:
        """Describe current settings with a blank credential to preserve storage."""
        return {
            "name": self.agent.name,
            "model_identifier": self.agent.model_identifier,
            "default_instructions": self.agent.default_instructions,
            "enabled": "on",
            "base_url": self.agent.base_url,
            "request_timeout_seconds": 45,
            "max_tokens": 1234,
            "max_tool_calls": 7,
            "max_duration_seconds": 120,
            "parameter__temperature": "0.4",
            "parameter__stop_sequences": "halt",
            "parameter__parallel_tool_calls": "true",
            "credential__api_key": "",
            **overrides,
        }

    def select_provider(self, provider: str = "openai") -> None:
        """Advance to the populated configuration form using the inherited first step."""
        self.assertEqual(
            self.client.post(self.url, {"provider": provider}).status_code, 200
        )

    def test_detail_route_inherits_create_and_loads_settings(self) -> None:
        """Keep the two-step flow and show stored non-secret values in the detail frame."""
        self.assertEqual(resolve(self.url).func.view_class, ReconfigureAIAgentView)
        self.assertTrue(issubclass(ReconfigureAIAgentView, CreateAIAgentView))
        response = self.client.get(self.url)
        self.assertContains(response, 'data-wizard-total-steps="2"')
        self.assertEqual(response.context["selected_provider"], "openai")
        self.assertEqual(
            [item["name"] for item in response.context["tab_items"]],
            ["Details", "Reconfigure", "Delete", "Access"],
        )
        self.select_provider()
        response = self.client.get(self.url)
        form = response.context["form"]
        self.assertEqual(form["name"].value(), self.agent.name)
        self.assertEqual(form["parameter__temperature"].value(), 0.4)
        self.assertEqual(form["parameter__stop_sequences"].value(), "halt")
        self.assertEqual(form["max_tool_calls"].value(), 7)
        self.assertContains(response, "Save changes")
        self.assertNotContains(response, "existing-secret")
        self.assertNotIn("existing-secret", str(dict(self.client.session)))

    def create_test_object(self) -> AIAgent:
        """Use the configured agent as the detail-route object for request scenarios."""
        return self.agent

    def prepare_reconfiguration(self, scenario: RequestScenario) -> None:
        """Snapshot protected settings and select the provider before a final-step request."""
        self.encrypted_before = self.agent.credentials_encrypted.copy()
        self.parameters_before = self.agent.parameters.copy()
        self.client.force_login(self.user)
        self.select_provider()
        scenario.data = self.details(name="Renamed assistant")

    def blank_credentials_preserved(self, response: HttpResponse) -> bool:
        """Verify a blank credential keeps the record, creator, ciphertext and settings."""
        self.agent.refresh_from_db()
        self.assertEqual(AIAgent.objects.count(), 1)
        self.assertEqual(self.agent.name, "Renamed assistant")
        self.assertEqual(self.agent.credentials_encrypted, self.encrypted_before)
        self.assertEqual(self.agent.parameters, self.parameters_before)
        self.assertEqual(self.agent.default_instructions, "Keep these instructions")
        self.assertEqual(self.agent.created_by, self.user)
        self.assertEqual(self.agent.max_tokens, 1234)
        self.assertEqual(self.agent.base_url, "https://example.com/v1")
        return True

    def htmx_save_refreshes(self, response: HttpResponse) -> bool:
        """Refresh the full page and clear wizard state after an HTMX final submission."""
        self.assertEqual(response.headers["HX-Refresh"], "true")
        self.assertEqual(response.content, b"")
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.name, "Renamed assistant")
        self.assertNotIn(f"ai_agent_reconfigure_{self.agent.pk}", self.client.session)
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Declare preserved blank credentials, HTMX completion and denied access."""
        return [
            RequestScenario(
                name="Blank credentials preserve settings",
                method="POST",
                user=self.user,
                prepare=self.prepare_reconfiguration,
                expected=ExpectedResult(
                    status_code=302,
                    response_validators=self.blank_credentials_preserved,
                ),
            ),
            RequestScenario(
                name="HTMX save refreshes the page",
                method="POST",
                user=self.user,
                prepare=self.prepare_reconfiguration,
                headers={"hx-request": "true", "hx-target": "wizard-root"},
                expected=ExpectedResult(response_validators=self.htmx_save_refreshes),
            ),
            RequestScenario(
                name="Ungranted editor is denied",
                user=self.other,
                expected=ExpectedResult(status_code=403),
            ),
        ]

    def test_rotation_validation_and_provider_switch(self) -> None:
        """Encrypt replacements, reject invalid settings, and require new-provider credentials."""
        self.select_provider()
        response = self.client.post(
            self.url,
            self.details(
                parameter__temperature="9", credential__api_key="replacement-secret"
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "replacement-secret")
        self.agent.refresh_from_db()
        self.assertEqual(
            self.agent.validated_credentials().api_key.get_secret_value(),
            "existing-secret",
        )
        response = self.client.post(
            self.url, self.details(credential__api_key="replacement-secret")
        )
        self.assertEqual(response.status_code, 302)
        self.agent.refresh_from_db()
        self.assertEqual(
            self.agent.validated_credentials().api_key.get_secret_value(),
            "replacement-secret",
        )
        self.select_provider("anthropic")
        response = self.client.post(self.url, self.details())
        self.assertEqual(response.status_code, 200)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.provider, "openai")
        response = self.client.post(
            self.url, self.details(credential__api_key="anthropic-secret")
        )
        self.assertEqual(response.status_code, 302)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.provider, "anthropic")
        self.assertEqual(
            self.agent.validated_credentials().api_key.get_secret_value(),
            "anthropic-secret",
        )

    def test_use_grant_and_revoked_change_permissions_cannot_reconfigure(self) -> None:
        """Deny a granted agent user and an administrator whose change access was revoked."""
        grant = AIAgentAccess.objects.create(name="Use only", model=self.agent)
        grant.users.add(self.other)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.user)
        self.select_provider()
        self.user.is_superuser = False
        self.user.save()
        self.assertEqual(self.client.post(self.url, self.details()).status_code, 403)

    def test_default_layout_and_tab_order(self) -> None:
        """Expose only the two basic controls and access relation, in the requested tab order."""
        config = self.agent.bloomerp_config.detail_view_settings
        items = config.get_default_layout().rows[0].items
        self.assertEqual(
            [(item.id, item.colspan) for item in items],
            [("name", 1), ("enabled", 1), ("access", 2)],
        )
        tabs = config.tab_configurations[0].tabs
        self.assertEqual(
            [tab.name for tab in tabs], ["Details", "Reconfigure", "Delete", "Access"]
        )
        for tab in tabs:
            reverse(tab.url_name, args=[self.agent.pk])

    def test_reconfiguration_preserves_fields_outside_change_grants(self) -> None:
        """Permit authorized setting changes while preserving hidden parameters and credentials."""
        fields = {"provider", "name", "model_identifier"}
        content_type = ContentType.objects.get_for_model(AIAgent)
        for field in fields:
            ApplicationField.objects.get_or_create(
                content_type=content_type,
                field=field,
                defaults={"field_type": "CharField"},
            )
        policy = PolicyManager.create_policy(
            AIAgent,
            field_permissions=dict.fromkeys(fields, "change"),
            row_permissions=[
                RowPolicyRuleContent(conditions=[], permissions=["change"])
            ],
        )
        policy.assign_user(self.other)
        self.client.force_login(self.other)
        self.select_provider()
        response = self.client.post(
            self.url, {"name": "Limited update", "model_identifier": "existing-model"}
        )
        self.assertEqual(response.status_code, 302)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.name, "Limited update")
        self.assertEqual(self.agent.parameters["temperature"], 0.4)
        self.assertEqual(self.agent.max_tokens, 1234)
        self.assertEqual(
            self.agent.validated_credentials().api_key.get_secret_value(),
            "existing-secret",
        )
