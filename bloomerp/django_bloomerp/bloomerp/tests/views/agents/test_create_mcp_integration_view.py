"""Routed request scenarios for two-step MCP creation and outbound OAuth callbacks."""

import time
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from bloomerp.filters.definition import FilterCondition
from bloomerp.forms.agents.mcp_integration import MCPIntegrationForm
from bloomerp.models.agents import MCPConnection, MCPIntegration
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.mcp.oauth import seal, unseal
from bloomerp.tests.base import (
    BloomerpModelViewTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.tests.services.mcp.test_oauth import ENDPOINT, ISSUER, protocol_response
from bloomerp.views.agents.create_mcp_integration import CreateMCPIntegrationView
from django.http import HttpResponse
from django.test import override_settings
from django.urls import resolve, reverse


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class TestCreateMCPIntegrationView(BloomerpModelViewTestCase):
    """Exercise real routes, sessions, encrypted storage and normal create permissions."""

    model = MCPIntegration
    view_name = "add"
    auto_create_customers = False

    def details(self, **overrides: Any) -> dict[str, Any]:
        """Describe shared, no-auth server configuration with editable review metadata."""
        return {
            "name": "External tools",
            "endpoint_url": ENDPOINT,
            "enabled": "on",
            "connection_mode": "shared",
            "authentication_type": "none",
            "oauth_client_id": "",
            "oauth_scopes": "",
            **overrides,
        }

    def fresh(self, scenario: RequestScenario) -> None:
        """Reset wizard state and start mocked outbound protocol requests for one scenario."""
        if scenario.user is not None:
            scenario.user.refresh_from_db()
        self.remote_patch = patch(
            "bloomerp.services.mcp.oauth.remote_request", side_effect=protocol_response
        )
        self.remote = self.remote_patch.start()
        self.client.force_login(scenario.user or self.admin_user)
        session = self.client.session
        session.pop(CreateMCPIntegrationView.session_key, None)
        session.save()

    def cleanup_remote(self, scenario: RequestScenario) -> None:
        """Remove outbound mocks after each isolated request scenario."""
        self.remote_patch.stop()

    def next(self, values: dict[str, Any]) -> HttpResponse:
        """Complete configuration using a localhost OAuth-compatible callback origin."""
        return self.client.post(
            reverse("mcp_integrations_add"), values, headers={"host": "localhost"}
        )

    def prepare_no_auth_review(self, scenario: RequestScenario) -> None:
        """Advance a public integration without saving any model records."""
        self.fresh(scenario)
        response = self.next(self.details())
        self.assertContains(response, 'data-wizard-step-index="1"')
        self.assertEqual(MCPIntegration.objects.count(), 0)
        self.remote.assert_not_called()

    def prepare_personal_review(self, scenario: RequestScenario) -> None:
        """Advance personal OAuth configuration without requesting admin authorization."""
        self.fresh(scenario)
        response = self.next(
            self.details(connection_mode="personal", authentication_type="oauth")
        )
        self.assertContains(response, 'data-wizard-step-index="1"')
        self.remote.assert_not_called()

    def prepare_api_key_review(self, scenario: RequestScenario) -> None:
        """Verify a shared key and retain only encrypted credentials before review."""
        self.fresh(scenario)
        self.remote.side_effect = None
        self.remote.return_value = httpx.Response(200)
        response = self.next(
            self.details(authentication_type="api_key", api_key="wizard-key-secret")
        )
        self.assertContains(response, 'data-wizard-step-index="1"')
        self.assertNotContains(response, "wizard-key-secret")
        self.assertNotIn("wizard-key-secret", str(dict(self.client.session)))
        self.assertEqual(MCPConnection.objects.count(), 0)

    def begin_oauth(self, scenario: RequestScenario) -> None:
        """Start an actual discovery and authorization redirect in the same session."""
        self.fresh(scenario)
        response = self.next(
            self.details(
                authentication_type="oauth", oauth_client_id="registered-client"
            )
        )
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["resource"], [ENDPOINT])
        self.pending = unseal(
            self.client.session[CreateMCPIntegrationView.session_key]["pending_oauth"]
        )
        self.assertEqual(query["state"], [self.pending["state"]])
        self.assertNotIn(self.pending["verifier"], str(dict(self.client.session)))
        scenario.query_params = {
            "state": self.pending["state"],
            "code": "returned-code",
            "iss": ISSUER,
        }

    def prepare_oauth_review(self, scenario: RequestScenario) -> None:
        """Authorize shared OAuth credentials and return the wizard to editable review."""
        self.begin_oauth(scenario)
        callback = self.client.get(
            reverse("mcp_integrations_oauth_callback"), scenario.query_params
        )
        self.assertEqual(callback.status_code, 302)
        self.assertEqual(MCPIntegration.objects.count(), 0)
        scenario.query_params = None

    def bad_state(self, scenario: RequestScenario) -> None:
        """Replace a legitimate callback state with an unrecognized value."""
        self.begin_oauth(scenario)
        scenario.query_params["state"] = "wrong-state"

    def cancelled_oauth(self, scenario: RequestScenario) -> None:
        """Return an authorization denial with the original CSRF state."""
        self.begin_oauth(scenario)
        scenario.query_params = {
            "state": self.pending["state"],
            "error": "access_denied",
            "error_description": "remote-secret-message",
            "iss": ISSUER,
        }

    def wrong_issuer(self, scenario: RequestScenario) -> None:
        """Return a code issued by an unexpected authorization server."""
        self.begin_oauth(scenario)
        scenario.query_params["iss"] = "https://wrong.example.com"

    def wrong_issuer_error(self, scenario: RequestScenario) -> None:
        """Return an untrusted error whose issuer must be rejected before interpreting it."""
        self.wrong_issuer(scenario)
        scenario.query_params["error"] = "access_denied"

    def missing_issuer(self, scenario: RequestScenario) -> None:
        """Omit issuer identification when the authorization server advertises it."""
        self.begin_oauth(scenario)
        scenario.query_params.pop("iss")

    def expired_review(self, scenario: RequestScenario) -> None:
        """Expire issued credentials while the administrator is reviewing settings."""
        self.prepare_oauth_review(scenario)
        session = self.client.session
        wizard = session[CreateMCPIntegrationView.session_key]
        wizard["connection"]["expires_at"] = time.time() - 1
        session[CreateMCPIntegrationView.session_key] = wizard
        session.save()

    def expired_oauth(self, scenario: RequestScenario) -> None:
        """Expire the pending authorization before its callback returns."""
        self.begin_oauth(scenario)
        self.pending["started_at"] = time.time() - 1000
        session = self.client.session
        wizard = session[CreateMCPIntegrationView.session_key]
        wizard["pending_oauth"] = seal(self.pending)
        session[CreateMCPIntegrationView.session_key] = wizard
        session.save()

    def different_owner(self, scenario: RequestScenario) -> None:
        """Bind pending state to a different account before a callback request."""
        self.begin_oauth(scenario)
        self.pending["owner_id"] = str(self.normal_user.pk)
        session = self.client.session
        wizard = session[CreateMCPIntegrationView.session_key]
        wizard["pending_oauth"] = seal(self.pending)
        session[CreateMCPIntegrationView.session_key] = wizard
        session.save()

    def failed_token(self, scenario: RequestScenario) -> None:
        """Make the token endpoint deny the authorization code without exposing its body."""
        self.begin_oauth(scenario)
        self.remote.side_effect = None
        self.remote.return_value = httpx.Response(
            400,
            request=httpx.Request("POST", "https://auth.example.com/token"),
            json={
                "error": "invalid_grant",
                "error_description": "remote-secret-message",
            },
        )

    def replayed_callback(self, scenario: RequestScenario) -> None:
        """Complete a callback once and then send exactly the same callback again."""
        self.begin_oauth(scenario)
        self.client.get(
            reverse("mcp_integrations_oauth_callback"), scenario.query_params
        )

    def api_key_denied(self, scenario: RequestScenario) -> None:
        """Return HTTP unauthorized to the shared-key check."""
        self.fresh(scenario)
        self.remote.side_effect = None
        self.remote.return_value = httpx.Response(401)

    def grant_creation(self, scenario: RequestScenario) -> None:
        """Grant the normal creator real row/field policies, without connection-model access."""
        self.normal_user.is_staff = True
        self.normal_user.save()
        policy = PolicyManager.create_policy(
            MCPIntegration,
            field_permissions=dict.fromkeys(MCPIntegrationForm.Meta.fields, "add"),
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["add"],
                    conditions=[
                        FilterCondition(
                            field_path="enabled", lookup_id="equals", value=True
                        )
                    ],
                )
            ],
            global_permissions=["add"],
        )
        PolicyManager.assign(policy, self.normal_user)
        self.prepare_no_auth_review(scenario)

    def revoke_creation(self, scenario: RequestScenario) -> None:
        """Revoke create authorization after the administrator reaches review."""
        self.prepare_no_auth_review(scenario)
        self.admin_user.is_superuser = False
        self.admin_user.save()

    def disjoint_field_grants(self, scenario: RequestScenario) -> None:
        """Grant fields on a different row so their union cannot authorize this candidate."""
        self.normal_user.is_staff = True
        self.normal_user.save()
        for fields, name in (
            (set(MCPIntegrationForm.Meta.fields), "Other tools"),
            ({"name"}, "External tools"),
        ):
            policy = PolicyManager.create_policy(
                MCPIntegration,
                field_permissions=dict.fromkeys(fields, "add"),
                row_permissions=[
                    RowPolicyRuleContent(
                        permissions=["add"],
                        conditions=[
                            FilterCondition(
                                field_path="name", lookup_id="equals", value=name
                            )
                        ],
                    )
                ],
                global_permissions=["add"],
            )
            PolicyManager.assign(policy, self.normal_user)
        self.fresh(scenario)

    def review_without_rows(self, response: HttpResponse) -> bool:
        """Verify exactly two steps and deferred database creation."""
        self.assertContains(response, 'data-wizard-step-index="1"')
        self.assertContains(response, 'data-wizard-total-steps="2"')
        self.assertEqual(MCPIntegration.objects.count(), 0)
        self.assertEqual(MCPConnection.objects.count(), 0)
        return True

    def public_saved(self, response: HttpResponse) -> bool:
        """Verify review edits persist without a credential account."""
        integration = MCPIntegration.objects.get()
        self.assertEqual(integration.name, "Reviewed tools")
        self.assertEqual(MCPConnection.objects.count(), 0)
        return True

    def personal_saved(self, response: HttpResponse) -> bool:
        """Verify personal-mode creation leaves every user account unlinked."""
        integration = MCPIntegration.objects.get()
        self.assertEqual(integration.connection_mode, "personal")
        self.assertEqual(integration.authentication_type, "oauth")
        self.assertEqual(MCPConnection.objects.count(), 0)
        self.remote.assert_not_called()
        return True

    def key_saved(self, response: HttpResponse) -> bool:
        """Verify atomic persistence creates only an encrypted shared connection."""
        connection = MCPConnection.objects.get()
        self.assertIsNone(connection.user_id)
        self.assertEqual(connection.status, "ready")
        self.assertEqual(
            connection.validated_credentials().api_key.get_secret_value(),
            "wizard-key-secret",
        )
        self.assertNotIn("wizard-key-secret", str(connection.credentials_encrypted))
        self.assertNotIn(CreateMCPIntegrationView.session_key, self.client.session)
        return True

    def oauth_saved(self, response: HttpResponse) -> bool:
        """Verify authorized tokens are encrypted and the connection preserves their expiry."""
        connection = MCPConnection.objects.get()
        self.assertEqual(connection.status, "ready")
        self.assertIsNotNone(connection.expires_at)
        self.assertEqual(
            connection.validated_credentials().access_token.get_secret_value(),
            "issued-token-secret",
        )
        self.assertNotIn("issued-token-secret", str(connection.credentials_encrypted))
        self.assertNotIn("issued-token-secret", str(dict(self.client.session)))
        return True

    def authentication_failed(self, response: HttpResponse) -> bool:
        """Verify rejected/cancelled callbacks return to configuration with no stored tokens."""
        state = self.client.session.get(CreateMCPIntegrationView.session_key, {})
        self.assertFalse(state.get("review_ready"))
        self.assertIsNone(state.get("connection"))
        self.assertEqual(MCPIntegration.objects.count(), 0)
        self.assertNotIn("remote-secret-message", str(state))
        if (
            response.wsgi_request.GET.get("error")
            and response.wsgi_request.GET.get("iss") == "https://wrong.example.com"
        ):
            self.assertIn("issuer", state["__wizard_error"]["message"])
            self.assertNotIn("cancelled", state["__wizard_error"]["message"])
        token_calls = [
            call
            for call in self.remote.call_args_list
            if call.args[1] == "https://auth.example.com/token"
        ]
        if self.remote.return_value.status_code != 400:
            self.assertLessEqual(len(token_calls), 1)
        return True

    def authentication_invalidated(self, response: HttpResponse) -> bool:
        """Verify review edits invalidate old credentials and require reconnecting."""
        self.assertContains(response, 'data-wizard-step-index="0"')
        self.assertFalse(
            self.client.session[CreateMCPIntegrationView.session_key].get("connection")
        )
        self.assertEqual(MCPIntegration.objects.count(), 0)
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Declare two-step creation, outbound callbacks, review edits and permission failures."""
        admin = self.admin_user
        scenarios = [
            RequestScenario(
                name="Create route is the real wizard",
                user=admin,
                prepare=self.fresh,
                expected=ExpectedResult(
                    response_validators=self.contains_text('data-wizard-step-index="0"')
                ),
            ),
            RequestScenario(
                name="Direct step query cannot skip configuration",
                user=admin,
                prepare=self.fresh,
                query_params={"step": 1},
                expected=ExpectedResult(
                    response_validators=self.contains_text('data-wizard-step-index="0"')
                ),
            ),
            RequestScenario(
                name="No-auth next reaches review without saving",
                user=admin,
                method="POST",
                prepare=self.fresh,
                data=self.details(),
                expected=ExpectedResult(response_validators=self.review_without_rows),
            ),
            RequestScenario(
                name="No-auth final save persists review edits",
                user=admin,
                method="POST",
                prepare=self.prepare_no_auth_review,
                data=self.details(name="Reviewed tools"),
                expected=ExpectedResult(
                    status_code=302, response_validators=self.public_saved
                ),
            ),
            RequestScenario(
                name="Personal OAuth requires no admin account",
                user=admin,
                method="POST",
                prepare=self.prepare_personal_review,
                data=self.details(
                    connection_mode="personal", authentication_type="oauth"
                ),
                expected=ExpectedResult(
                    status_code=302, response_validators=self.personal_saved
                ),
            ),
            RequestScenario(
                name="Shared API key saves encrypted on final review",
                user=admin,
                method="POST",
                prepare=self.prepare_api_key_review,
                data=self.details(authentication_type="api_key"),
                expected=ExpectedResult(
                    status_code=302, response_validators=self.key_saved
                ),
            ),
            RequestScenario(
                name="Editing endpoint requires a replacement key",
                user=admin,
                method="POST",
                prepare=self.prepare_api_key_review,
                data=self.details(
                    authentication_type="api_key",
                    endpoint_url="https://changed.example.com/mcp",
                ),
                expected=ExpectedResult(
                    response_validators=self.authentication_invalidated
                ),
            ),
            RequestScenario(
                name="Shared API key denial stays on configuration",
                user=admin,
                method="POST",
                prepare=self.api_key_denied,
                data=self.details(
                    authentication_type="api_key", api_key="denied-key-secret"
                ),
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("rejected"),
                        self.does_not_contain_text("denied-key-secret"),
                    ]
                ),
            ),
            RequestScenario(
                name="OAuth authorization callback returns to review",
                user=admin,
                prepare=self.begin_oauth,
                view_name="oauth_callback",
                expected=ExpectedResult(
                    status_code=302, response_validators=self.oauth_review_ready
                ),
            ),
            RequestScenario(
                name="OAuth final save creates encrypted shared account",
                user=admin,
                method="POST",
                prepare=self.prepare_oauth_review,
                data=self.details(
                    authentication_type="oauth", oauth_client_id="registered-client"
                ),
                expected=ExpectedResult(
                    status_code=302, response_validators=self.oauth_saved
                ),
            ),
            RequestScenario(
                name="Editing OAuth endpoint redirects to a fresh authorization",
                user=admin,
                method="POST",
                prepare=self.prepare_oauth_review,
                data=self.details(
                    authentication_type="oauth",
                    oauth_client_id="registered-client",
                    oauth_scopes="different:scope",
                ),
                headers={"host": "localhost"},
                expected=ExpectedResult(
                    status_code=302, response_validators=self.fresh_authorization
                ),
            ),
            RequestScenario(
                name="Ordinary creator uses standard model policies",
                user=self.normal_user,
                method="POST",
                prepare=self.grant_creation,
                data=self.details(name="Reviewed tools"),
                expected=ExpectedResult(
                    status_code=302, response_validators=self.public_saved
                ),
            ),
            RequestScenario(
                name="Row policy rejects final review changes",
                user=self.normal_user,
                method="POST",
                prepare=self.grant_creation,
                data=self.details(enabled=""),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Field grants from unrelated rows cannot authorize creation",
                user=self.normal_user,
                method="POST",
                prepare=self.disjoint_field_grants,
                data=self.details(),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Expired OAuth credentials cannot be saved",
                user=admin,
                method="POST",
                prepare=self.expired_review,
                data=self.details(
                    authentication_type="oauth", oauth_client_id="registered-client"
                ),
                expected=ExpectedResult(
                    response_validators=self.authentication_invalidated
                ),
            ),
            RequestScenario(
                name="HTMX Next redirects the browser to OAuth",
                user=admin,
                method="POST",
                prepare=self.fresh,
                headers={"host": "localhost", "HX-Request": "true"},
                data=self.details(
                    authentication_type="oauth", oauth_client_id="registered-client"
                ),
                expected=ExpectedResult(response_validators=self.htmx_oauth_redirect),
            ),
            RequestScenario(
                name="Invalid endpoint never echoes supplied secrets",
                user=admin,
                method="POST",
                prepare=self.fresh,
                data=self.details(
                    endpoint_url="http://example.com/mcp",
                    authentication_type="api_key",
                    api_key="secret-to-hide",
                ),
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("HTTPS"),
                        self.does_not_contain_text("secret-to-hide"),
                    ]
                ),
            ),
            RequestScenario(
                name="Creator cannot change fields after permissions revoked",
                user=admin,
                method="POST",
                prepare=self.revoke_creation,
                data=self.details(),
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="User without create policies is denied",
                user=self.normal_user,
                prepare=self.fresh,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Client metadata is public and has no secrets",
                view_name="oauth_client_metadata",
                prepare=self.fresh,
                expected=ExpectedResult(
                    response_validators=[
                        self.key_in_json("redirect_uris"),
                        self.json_key_equals("token_endpoint_auth_method", "none"),
                    ]
                ),
            ),
        ]
        for name, preparation in (
            ("Wrong callback state rejected", self.bad_state),
            ("Cancelled OAuth rejected", self.cancelled_oauth),
            ("Wrong OAuth issuer rejected", self.wrong_issuer),
            ("Wrong OAuth issuer error rejected", self.wrong_issuer_error),
            ("Missing OAuth issuer rejected", self.missing_issuer),
            ("Expired callback rejected", self.expired_oauth),
            ("Other account callback rejected", self.different_owner),
            ("Token exchange failure rejected", self.failed_token),
            ("Replayed callback rejected", self.replayed_callback),
        ):
            scenarios.append(
                RequestScenario(
                    name=name,
                    user=admin,
                    prepare=preparation,
                    view_name="oauth_callback",
                    expected=ExpectedResult(
                        status_code=302, response_validators=self.authentication_failed
                    ),
                )
            )
        for scenario in scenarios:
            scenario.cleanup = self.cleanup_remote
        return scenarios

    def htmx_oauth_redirect(self, response: HttpResponse) -> bool:
        """Verify HTMX follows a full-browser redirect rather than swapping an external page."""
        self.assertIn("https://auth.example.com/authorize", response["HX-Redirect"])
        self.assertNotIn("issued-token-secret", response["HX-Redirect"])
        return True

    def oauth_review_ready(self, response: HttpResponse) -> bool:
        """Verify the callback redirects to step two with no tokens in session plaintext."""
        state = self.client.session[CreateMCPIntegrationView.session_key]
        self.assertTrue(state["review_ready"])
        self.assertEqual(state["__wizard_step"], 1)
        self.assertNotIn("issued-token-secret", str(state))
        self.assertNotIn("refresh-token-secret", str(state))
        self.assertIsNone(state["pending_oauth"])
        return True

    def fresh_authorization(self, response: HttpResponse) -> bool:
        """Verify an OAuth settings edit starts over and discards the old token envelope."""
        state = self.client.session[CreateMCPIntegrationView.session_key]
        self.assertIsNone(state.get("connection"))
        self.assertFalse(state.get("review_ready"))
        self.assertTrue(state.get("pending_oauth"))
        self.assertIn("auth.example.com/authorize", response["Location"])
        return True

    def test_model_create_route_override(self) -> None:
        """Verify the model's standard create action resolves to the wizard class."""
        self.assertIs(
            resolve(reverse("mcp_integrations_add")).func.view_class,
            CreateMCPIntegrationView,
        )
