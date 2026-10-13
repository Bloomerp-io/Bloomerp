"""Verify shared wizard reconfiguration and its authorization boundary."""

import json
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.test import override_settings
from bloomerp.config.definition import BloomerpConfig
from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.views.communication.create_email_account import EmailAccountSettingsForm
from bloomerp.tests.base import BloomerpDetailViewTestCase, RequestScenario, ExpectedResult


class TestReconfigureEmailAccountView(BloomerpDetailViewTestCase):
    model = EmailAccount
    view_name = "reconfigure_email_account"

    def prepare_account(self, scenario: RequestScenario) -> None:
        """Create an encrypted existing account without contacting a provider."""
        self.secret_settings = override_settings(
            BLOOMERP_CONFIG=BloomerpConfig(email_secret_key="test-secret")
        )
        self.secret_settings.enable()
        self.account = EmailAccount.objects.create(
            email_address="existing@example.com",
            password="stored-password",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
            mailboxes=["INBOX", "Sent"],
        )
        scenario.view_kwargs = {"pk": str(self.account.pk)}

    def prepare_mapping_step(self, scenario: RequestScenario) -> None:
        """Walk the shared provider/settings steps using a blank password to retain it."""
        self.advance_to_mapping_step(scenario, omit_password=False)

    def prepare_mapping_without_password(self, scenario: RequestScenario) -> None:
        """Reach the final step when the browser omits the password field entirely."""
        self.advance_to_mapping_step(scenario, omit_password=True)

    def advance_to_mapping_step(self, scenario: RequestScenario, *, omit_password: bool) -> None:
        """Validate reconfiguration with a blank or omitted password without contacting a provider."""
        self.client.force_login(self.admin_user)
        url = self.get_endpoint(self.view_name, scenario.view_kwargs)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"provider": "imap"}).status_code, 200)
        with patch.object(
            ImapSmtpAdapter, "validate_connection", return_value=["INBOX", "Sent"]
        ):
            settings = {
                "email_address": self.account.email_address,
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_security": "ssl_tls",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_security": "starttls",
            }
            if not omit_password:
                settings["password"] = ""
            response = self.client.post(url, settings)
        self.assertEqual(response.context_data["step_index"], 2)
        self.account.refresh_from_db()
        self.assertEqual(self.account.mailboxes["INBOX"]["label"], "INBOX")

    def cleanup_settings(self, scenario: RequestScenario) -> None:
        """Restore the project's secret configuration after each scenario."""
        self.secret_settings.disable()

    def grant_change_access(self, scenario: RequestScenario) -> None:
        """Allow editing the account without granting permission to create accounts."""
        self.normal_user.is_staff = True
        self.normal_user.save(update_fields=["is_staff"])
        fields = [*EmailAccountSettingsForm.Meta.fields, "provider", "mailboxes"]
        policy = PolicyManager.create_policy(
            EmailAccount,
            field_permissions=dict.fromkeys(fields, "change"),
            row_permissions=[RowPolicyRuleContent(conditions=[], permissions=["change"])],
        )
        policy.assign_user(self.normal_user)

    def grant_add_access(self, scenario: RequestScenario) -> None:
        """Grant creation alone to verify it cannot authorize reconfiguration."""
        self.normal_user.is_staff = True
        self.normal_user.save(update_fields=["is_staff"])
        self.normal_user.user_permissions.add(Permission.objects.get(
            content_type=ContentType.objects.get_for_model(EmailAccount),
            codename="add_emailaccount",
        ))

    def saved_existing_account(self, response: HttpResponse) -> bool:
        """Check mapping changes preserve the account identity and stored password."""
        self.account.refresh_from_db()
        return (
            self.account.mailboxes["INBOX"]["label"] == "Customer mail"
            and self.account.get_password_secret() == "stored-password"
            and EmailAccount.objects.filter(
                email_address="existing@example.com"
            ).count()
            == 1
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover successful reconfiguration and a user without account permission."""
        return [
            RequestScenario(
                name="Change permission permits reconfiguration without add permission",
                user=self.normal_user,
                prepare=[self.prepare_account, self.grant_change_access],
                cleanup=self.cleanup_settings,
                expected=ExpectedResult(status_code=200, response_validators=self.has_account_context),
            ),
            RequestScenario(
                name="Add permission alone cannot reconfigure an existing account",
                user=self.normal_user,
                prepare=[self.prepare_account, self.grant_add_access],
                cleanup=self.cleanup_settings,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Render the existing account in the detail wizard",
                user=self.admin_user,
                prepare=self.prepare_account,
                cleanup=self.cleanup_settings,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=self.has_account_context,
                ),
            ),
            RequestScenario(
                name="Save mappings without recreating the account or clearing its secret",
                user=self.admin_user,
                method="POST",
                prepare=[self.prepare_account, self.prepare_mapping_step],
                cleanup=self.cleanup_settings,
                data={
                    "mailboxes": json.dumps(
                        {
                            "INBOX": {"label": "Customer mail", "main_folder": True},
                            "Sent": {"label": "Sent", "sent_folder": True},
                        }
                    )
                },
                expected=ExpectedResult(
                    status_code=302, response_validators=self.saved_existing_account
                ),
            ),
            RequestScenario(
                name="Omitted password preserves the stored secret through the final save",
                user=self.admin_user,
                method="POST",
                prepare=[self.prepare_account, self.prepare_mapping_without_password],
                cleanup=self.cleanup_settings,
                data={
                    "mailboxes": json.dumps({
                        "INBOX": {"label": "Customer mail", "main_folder": True},
                        "Sent": {"label": "Sent", "sent_folder": True},
                    })
                },
                expected=ExpectedResult(status_code=302, response_validators=self.saved_existing_account),
            ),
            RequestScenario(
                name="Deny reconfiguration without object access",
                user=self.normal_user,
                prepare=self.prepare_account,
                cleanup=self.cleanup_settings,
                expected=ExpectedResult(status_code=403),
            ),
        ]

    def has_account_context(self, response: HttpResponse) -> bool:
        """Verify detail framing receives the account and provider is preselected."""
        return (
            response.context_data["object"].pk == self.account.pk
            and response.context_data["selected_provider"] == self.account.provider
            and "stored-password" not in response.content.decode()
        )
