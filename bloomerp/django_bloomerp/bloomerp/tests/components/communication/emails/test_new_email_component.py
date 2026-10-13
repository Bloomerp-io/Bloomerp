"""Request contracts for the shared object/inbox email composer."""

from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.http import HttpResponse

from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.models import DocumentTemplate, EmailAccount, EmailDraft, User
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import BloomerpComponentTestCase, ExpectedResult, RequestScenario


class TestNewEmailComponent(BloomerpComponentTestCase):
    """Exercise context, sender access, variable rendering, and draft lifecycle."""

    view_name = "components_new_email"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create two senders, matching/global templates, and a user email target."""
        super().setUp()
        self.account = EmailAccount.objects.create(name="Primary", email_address="sender@example.com")
        self.other_account = EmailAccount.objects.create(name="Other", email_address="other@example.com")
        self.admin_user.default_email_account = self.account
        self.admin_user.save(update_fields=["default_email_account"])
        self.normal_user.email = "recipient@example.com"
        self.normal_user.first_name = "Ada"
        self.normal_user.save(update_fields=["email", "first_name"])
        self.content_type = ContentType.objects.get_for_model(User)
        self.template = DocumentTemplate.objects.create(
            name="Matching template", template="<p>Hello {{ user.first_name }}, {{ vars.note }}</p>",
            free_variables=[{"slug": "note", "label": "Note", "type": "text", "required": True}],
        )
        self.template.content_types.add(self.content_type)
        self.second_template = DocumentTemplate.objects.create(
            name="Closing", template="<p>{{ vars.closing }}</p>",
            free_variables=[{"slug": "closing", "label": "Closing", "type": "text", "required": True}],
        )
        self.global_template = DocumentTemplate.objects.create(name="Generic template", template="<p>Generic</p>")
        self.multiroot_template = DocumentTemplate.objects.create(
            name="Multiple roots", template="{{ user.first_name }} / {{ email_account.email_address }}",
        )
        self.multiroot_template.content_types.add(self.content_type, ContentType.objects.get_for_model(EmailAccount))
        self.unrelated_template = DocumentTemplate.objects.create(name="Unrelated template")
        self.unrelated_template.content_types.add(ContentType.objects.get_for_model(EmailAccount))
        inbox = Inbox.objects.create(user=self.normal_user, name="Shared mail")
        self.folder = InboxFolder.objects.create(inbox=inbox, type="email", related_object_id=str(self.account.pk))
        self.object_data = {"content_type_id": str(self.content_type.pk), "object_id": str(self.normal_user.pk)}
        self.message = {
            **self.object_data, "email_account_id": str(self.account.pk),
            "document_template_id": str(self.template.pk), "template_args-note": "Welcome",
            "to": "recipient@example.com", "subject": "A personal message",
            "body": "<p>Edited {{ user.first_name }}: {{ vars.note }}</p>",
        }

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover rendering, scoped access, immutable templates, and private autosave."""
        return [
            RequestScenario(name="Anonymous composer requires login", expected=ExpectedResult(status_code=302)),
            RequestScenario(
                name="Object composer prefills recipient and exposes the shared template command",
                user=self.admin_user, query_params={**self.object_data, "email_field": "email"},
                expected=ExpectedResult(response_validators=[
                    self.contains_text('value="recipient@example.com"'),
                    self.contains_text("data-template-search-url"), self.selected_default,
                ]),
            ),
            RequestScenario(
                name="Inbox sharing continues to grant composing without model policies",
                user=self.normal_user, query_params={"folder_id": str(self.folder.pk)},
                expected=ExpectedResult(response_validators=self.contains_text("sender@example.com")),
            ),
            RequestScenario(
                name="Group-shared inbox grants sender access",
                user=self.normal_user, query_params={"folder_id": str(self.folder.pk)},
                prepare=self.share_inbox_with_group,
                expected=ExpectedResult(response_validators=self.contains_text("sender@example.com")),
            ),
            RequestScenario(
                name="No-policy user cannot open an arbitrary object",
                user=self.normal_user, query_params={**self.object_data, "email_field": "email"},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Recipient field must be readable",
                user=self.normal_user, query_params={**self.object_data, "email_field": "email"},
                prepare=self.grant_name_only, headers={"Accept": "application/json"},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="A user cannot forge a sender outside their inbox access",
                method="POST", user=self.normal_user,
                data={"email_account_id": str(self.other_account.pk), "to": "a@example.com", "body": "Hello"},
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Template load returns unchanged content and prefilled root form",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data=self.message, expected=ExpectedResult(response_validators=self.template_copy),
            ),
            RequestScenario(
                name="Templates with other content types are accepted",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "document_template_id": str(self.unrelated_template.pk)},
                expected=ExpectedResult(status_code=200),
            ),
            RequestScenario(
                name="Preview combines variables from all inserted templates",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "preview": "true",
                      "document_template_id": [str(self.template.pk), str(self.second_template.pk)],
                      "template_args-closing": "Goodbye",
                      "body": "{{ vars.note }} / {{ vars.closing }}"},
                expected=ExpectedResult(response_validators=self.json_key_equals("html", "Welcome / Goodbye")),
            ),
            RequestScenario(
                name="Earlier template variables remain required",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "preview": "true",
                      "document_template_id": [str(self.template.pk), str(self.second_template.pk)],
                      "template_args-note": "", "template_args-closing": "Goodbye"},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Preview resolves the edited body and supplied variables",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "preview": "true"},
                expected=ExpectedResult(response_validators=self.json_key_equals("html", "<p>Edited Ada: Welcome</p>")),
            ),
            RequestScenario(
                name="Root object selectors retain the foreign field widget",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "document_template_id": str(self.multiroot_template.pk)},
                expected=ExpectedResult(response_validators=self.root_choices),
            ),
            RequestScenario(
                name="Additional content-type roots resolve from scoped form choices",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "preview": "true", "document_template_id": str(self.multiroot_template.pk),
                      "template_args-emailaccount": str(self.account.pk), "body": self.multiroot_template.template},
                expected=ExpectedResult(response_validators=self.json_key_equals("html", "Ada / sender@example.com")),
            ),
            RequestScenario(
                name="Additional content-type roots cannot bypass row permissions",
                view_name="components_email_template", method="POST", user=self.normal_user,
                prepare=self.grant_template_and_name,
                data={**self.message, "preview": "true", "document_template_id": str(self.multiroot_template.pk),
                      "template_args-emailaccount": str(self.other_account.pk), "body": self.multiroot_template.template},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Missing required template variable blocks preview",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "preview": "true", "template_args-note": ""},
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="A template cannot read a field outside the user's grants",
                view_name="components_email_template", method="POST", user=self.normal_user,
                prepare=self.grant_template_and_name,
                data={**self.message, "preview": "true", "body": "{{ user.email }}"},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Document table cannot bypass field checks through private attributes",
                view_name="components_email_template", method="POST", user=self.normal_user,
                prepare=self.grant_template_and_name,
                data={**self.message, "preview": "true", "body": '{% document_table objects "_object.email" %}'},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Document table supports authorized field values",
                view_name="components_email_template", method="POST", user=self.admin_user,
                data={**self.message, "preview": "true", "body": '{% document_table objects "first_name" %}'},
                expected=ExpectedResult(response_validators=self.contains_text("Ada")),
            ),
            RequestScenario(
                name="Send uses edited body and selected account and deletes only its draft",
                method="POST", user=self.admin_user, data=dict(self.message),
                prepare=[self.own_draft, self.mock_send], cleanup=self.stop_send,
                headers={"Accept": "application/json"},
                expected=ExpectedResult(response_validators=self.sent_message),
            ),
            RequestScenario(
                name="Send failure retains the private draft",
                method="POST", user=self.admin_user, data=dict(self.message),
                prepare=[self.own_draft, self.mock_send, self.fail_send], cleanup=self.stop_send,
                headers={"Accept": "application/json"},
                expected=ExpectedResult(status_code=400, response_validators=self.draft_retained),
            ),
        ]

    def share_inbox_with_group(self, _scenario: RequestScenario) -> None:
        """Grant inbox access through a group rather than source ownership."""
        group = Group.objects.create(name="Email team")
        self.normal_user.groups.add(group)
        self.folder.inbox.user = self.admin_user
        self.folder.inbox.save(update_fields=["user"])
        self.folder.inbox.shared_with_groups.add(group)

    def selected_default(self, response: HttpResponse) -> bool:
        """Verify the accessible user preference is selected in the composer."""
        return response.context["email_account"].pk == self.account.pk

    def template_copy(self, response: HttpResponse) -> bool:
        """Ensure loading copies raw placeholders and omits the preset root input."""
        payload = response.json()
        return payload["body"] == self.template.template and 'name="template_args-note"' in payload["form_html"] and 'name="template_args-user"' not in payload["form_html"]

    def grant_name_only(self, _scenario: RequestScenario) -> None:
        """Give the normal user row access while withholding the email field."""
        policy = PolicyManager.create_policy(
            model_or_content_type=User, global_permissions=["view"],
            field_permissions={"first_name": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)

    def grant_template_and_name(self, scenario: RequestScenario) -> None:
        """Allow template use but retain restricted access to recipient data."""
        self.grant_name_only(scenario)
        policy = PolicyManager.create_policy(
            model_or_content_type=DocumentTemplate, global_permissions=["view"],
            field_permissions={"__all__": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)

    def own_draft(self, scenario: RequestScenario) -> None:
        """Attach an existing owner draft to the operation under test."""
        self.draft = EmailDraft.objects.create(user=self.admin_user, payload={"body": "old"})
        scenario.data["draft_id"] = str(self.draft.pk)

    def mock_send(self, _scenario: RequestScenario) -> None:
        """Replace actual SMTP delivery with a checked adapter call."""
        self.send_patch = patch.object(ImapSmtpAdapter, "send_email", autospec=True, return_value="<test@example.com>")
        self.send_mock: Mock = self.send_patch.start()

    def stop_send(self, _scenario: RequestScenario) -> None:
        """Restore the adapter after each send scenario."""
        self.send_patch.stop()

    def fail_send(self, _scenario: RequestScenario) -> None:
        """Simulate provider validation failure without contacting any mail server."""
        self.send_mock.side_effect = ValidationError("SMTP unavailable")

    def sent_message(self, response: HttpResponse) -> bool:
        """Confirm edited content was sent while the reusable template was unchanged."""
        self.send_mock.assert_called_once()
        self.template.refresh_from_db()
        args, kwargs = self.send_mock.call_args
        return (
            args[0].email_account.pk == self.account.pk
            and kwargs["body_html"] == "<p>Edited Ada: Welcome</p>"
            and not EmailDraft.objects.filter(pk=self.draft.pk).exists()
            and self.template.template.startswith("<p>Hello")
            and "message" in response.json()
        )

    def draft_retained(self, _response: HttpResponse) -> bool:
        """Leave the draft available after an unsuccessful send."""
        return EmailDraft.objects.filter(pk=self.draft.pk).exists()


    def root_choices(self, response: HttpResponse) -> bool:
        """Ensure the template form retains its standard related-object search widget."""
        html = response.json()["form_html"]
        return (
            'bloomerp-component="foreign-field-widget"' in html
            and 'data-field-name="template_args-emailaccount"' in html
            and f'data-content-type-id="{ContentType.objects.get_for_model(EmailAccount).pk}"' in html
        )
