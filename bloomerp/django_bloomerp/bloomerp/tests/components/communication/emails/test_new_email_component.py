"""Request contracts for the shared object/inbox email composer."""

from unittest.mock import Mock, patch

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import HttpResponse

from bloomerp.communication.builtins.emails.base_adapter import (
    BloomerpEmail,
    EmailSendResult,
    EmailSendUnconfirmed,
)
from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.models import DocumentTemplate, EmailAccount, EmailDraft, User
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


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
                name="Provider acceptance is shown without claiming final delivery",
                method="POST", user=self.admin_user, data=dict(self.message),
                prepare=[self.own_draft, self.mock_send, self.accepted_send], cleanup=self.stop_send,
                headers={"Accept": "application/json"},
                expected=ExpectedResult(response_validators=self.accepted_message),
            ),
            RequestScenario(
                name="Send failure retains the private draft",
                method="POST", user=self.admin_user, data=dict(self.message),
                prepare=[self.own_draft, self.mock_send, self.fail_send], cleanup=self.stop_send,
                headers={"Accept": "application/json"},
                expected=ExpectedResult(status_code=400, response_validators=self.draft_retained),
            ),
            RequestScenario(
                name="Unconfirmed send retains correlation and prevents resubmitting the draft",
                method="POST", user=self.admin_user, data=dict(self.message),
                prepare=[self.own_draft, self.mock_send, self.unconfirmed_send], cleanup=self.stop_send,
                headers={"Accept": "application/json"},
                expected=ExpectedResult(status_code=202, response_validators=self.pending_send_retained),
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

    def unconfirmed_send(self, _scenario: RequestScenario) -> None:
        """Simulate a submitted draft whose remote send response was lost."""
        self.send_mock.side_effect = EmailSendUnconfirmed(EmailSendResult(
            provider_message_id="remote-pending-id", message_id="<pending@example.com>",
        ))

    def accepted_send(self, _scenario: RequestScenario) -> None:
        """Return provider acceptance and its remote message reference."""
        self.send_mock.return_value = EmailSendResult(
            provider_message_id="remote-accepted-id", message_id="<accepted@example.com>",
        )

    def accepted_message(self, response: HttpResponse) -> bool:
        """Distinguish an accepted transport request from final recipient delivery."""
        return self.sent_message(response) and response.json() == {
            "message": "Email accepted for sending.", "status": "accepted",
        }

    def pending_send_retained(self, response: HttpResponse) -> bool:
        """Retain a server-owned send guard across autosave and clear it on confirmation."""
        from bloomerp.communication.builtins.emails.actions import (
            _upsert_email_inbox_item_result,
        )

        self.draft.refresh_from_db()
        pending = InboxItem.objects.get(folder=self.folder, related_item_id="<pending@example.com>")
        self.assertEqual(self.draft.pending_send["provider_message_id"], "remote-pending-id")
        self.draft.payload = {"body": "Edited after the response was lost"}
        self.draft.email_account = self.other_account
        self.draft.save(update_fields=["payload", "email_account"])
        repeated = self.client.post(
            response.wsgi_request.path,
            {**self.message, "draft_id": str(self.draft.pk)},
            HTTP_ACCEPT="application/json",
        )
        retained = (
            response.json()["status"] == "unconfirmed"
            and repeated.status_code == 202
            and self.send_mock.call_count == 1
            and pending.raw_meta_data["provider_identity"] == "remote-pending-id"
            and pending.raw_meta_data["message_id"] == "<pending@example.com>"
            and pending.raw_meta_data["outbound_send_pending"] is True
        )
        _upsert_email_inbox_item_result(BloomerpEmail(
            provider=self.account.provider, provider_message_id="remote-pending-id",
            provider_message_id_scope="account", email_account_id=str(self.account.pk),
            mailbox="Sent", message_id="<pending@example.com>", is_draft=False,
        ), self.folder)
        return retained and not EmailDraft.objects.filter(pk=self.draft.pk).exists()

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


class TestEmailFileDelivery(BloomerpComponentTestCase):
    """Exercise current file grants and real MIME assembly through the composer endpoint."""

    view_name = "components_new_email"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create synthetic files and a mailbox, mocking only external SMTP transport."""
        import io
        from PIL import Image
        from unittest.mock import MagicMock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from bloomerp.models import FileNode, FileReference

        super().setUp()
        self.account = EmailAccount.objects.create(name="Mail", email_address="sender@example.com", smtp_host="smtp.example.com", smtp_port=587, save_sent_emails=False)
        inbox = Inbox.objects.create(user=self.normal_user, name="Mail")
        self.folder = InboxFolder.objects.create(inbox=inbox, type="email", related_object_id=str(self.account.pk))
        self.document = FileNode.objects.create(kind="FILE", name="Display title", created_by=self.normal_user, content=SimpleUploadedFile("original.pdf", b"original PDF bytes", content_type="application/pdf"))
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
        self.image_bytes = buffer.getvalue()
        self.image = FileNode.objects.create(kind="FILE", created_by=self.normal_user, content=SimpleUploadedFile("image.png", self.image_bytes, content_type="image/png"))
        self.customer = self.create_customer("Private", "Owner", 30)
        self.private = FileNode.objects.create(kind="FILE", created_by=self.admin_user, content=SimpleUploadedFile("secret.png", self.image_bytes))
        from bloomerp.models import ApplicationField
        FileReference.objects.create(file=self.private, content_object=self.customer, application_field=ApplicationField.get_by_field(self.CustomerModel, "picture"))
        self.scenario_patches = []
        self.smtp = MagicMock()
        self.smtp.__enter__.return_value = self.smtp
        self.transport = patch.object(ImapSmtpAdapter, "_connect_smtp", return_value=self.smtp)
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.body = f'<p>Before</p><img data-reference-kind="file" data-target-id="{self.image.pk}" src="/api/files/serve/?file_id={self.image.pk}" alt="Diagram" style="width:120px"><p>After</p>'

    def selection(self, *identifiers: object) -> str:
        """Encode picker identities while deliberately supplying untrusted labels."""
        import json
        return json.dumps({"manual": [{"kind": "file", "target_id": str(pk), "label": "forged.exe"} for pk in identifiers], "fields": {}})

    def scenario(self, name: str, data: dict[str, object], *, status: int = 200, prepare: object = None, validator: object = None) -> RequestScenario:
        """Build an isolated authenticated send with default message inputs."""
        return RequestScenario(name=name, method="POST", user=self.normal_user,
            headers={"Accept": "application/json"}, data={"email_account_id": str(self.account.pk), "to": "recipient@example.com", "subject": "Files", "body": "<p>Hello</p>", **data},
            prepare=[self.reset_delivery, *([prepare] if prepare else [])],
            expected=ExpectedResult(status_code=status, response_validators=validator or (self.delivery_ok if status == 200 else self.delivery_blocked)))

    def reset_delivery(self, _scenario: RequestScenario) -> None:
        """Isolate mocked delivery counts between database-backed scenarios."""
        for active in self.scenario_patches:
            active.stop()
        self.scenario_patches.clear()
        if hasattr(self, "read_guard"):
            del self.read_guard
        self.smtp.reset_mock()

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover mixed delivery, identity validation, current grants, bytes, limits, and retries."""
        from uuid import uuid4
        from django.core.files.uploadedfile import SimpleUploadedFile
        private_html = f'<img data-reference-kind="file" data-target-id="{self.private.pk}" src="/private">'
        cases = [
            RequestScenario(name="Shared picker is rendered", user=self.normal_user, query_params={"folder_id": str(self.folder.pk)}, expected=ExpectedResult(response_validators=[self.contains_text('bloomerp-component="reference-attachments"'), self.contains_text('data-reference-upload'), self.does_not_contain_text('name="attachments"')])),
            self.scenario("Mixed stored, multipart and repeated inline images", {"object_references": self.selection(self.document.pk, self.image.pk), "body": self.body + self.body, "attachments": SimpleUploadedFile("legacy.txt", b"legacy", content_type="text/plain")}, validator=self.mixed_mime),
            self.scenario("URL-only stored image is embedded", {"body": f'<p>A</p><img src="http://testserver/api/files/serve/?file_id={self.image.pk}"><p>B</p>'}, validator=self.inline_mime),
            self.scenario("Upload endpoint and existing file share delivery", {"object_references": self.selection(self.document.pk)}, prepare=self.upload_new, validator=self.uploaded_mime),
            self.scenario("Removing selection preserves its original references", {"object_references": self.selection()}, validator=self.removal_preserves_source),
            self.scenario("Current owning field grants inline access", {"body": private_html}, prepare=self.grant_picture, validator=self.inline_mime),
            self.scenario("Other field grants cannot expose inline image", {"body": private_html}, status=400, prepare=self.grant_other_field),
            self.scenario("Correct field on a different row cannot expose inline image", {"body": private_html}, status=400, prepare=self.grant_other_row),
            self.scenario("Corrupt image bytes return validation error", {}, status=400, prepare=self.corrupt_image),
            self.scenario("Folders cannot be used as file attachments", {}, status=400, prepare=self.select_folder),
            self.scenario("Revoked grant blocks selection at send time", {"body": private_html}, status=400, prepare=self.revoke_picture),
            self.scenario("Mixed allowed/private selections fail before reading bytes", {"object_references": self.selection(self.document.pk), "body": private_html}, status=400, prepare=self.forbid_reads),
            self.scenario("Nonexistent file blocks complete message", {"object_references": self.selection(uuid4())}, status=400),
            self.scenario("Deleted inline image retains draft", {"body": self.body}, status=400, prepare=self.delete_image, validator=self.failed_draft_retained),
            self.scenario("Missing stored blob fails without SMTP", {"body": self.body}, status=400, prepare=self.missing_blob),
            self.scenario("Stale metadata cannot evade aggregate limit", {"object_references": self.selection(self.document.pk), "body": self.body}, status=400, prepare=self.small_limit),
            self.scenario("Non-image bytes cannot be an inline image", {"body": f'<img data-reference-kind="file" data-target-id="{self.document.pk}" src="private">'}, status=400),
            self.scenario("Unresolved clipboard image blocks sending", {"body": '<img src="blob:https://example.test/local">'}, status=400),
            self.scenario("Direct unpersisted image bytes block sending", {"body": '<img src="data:image/png;base64,AAAA">'}, status=400),
            self.scenario("Arbitrary remote image URL is not fetched", {"body": '<img src="https://external.example.test/image.png">'}, validator=self.external_unchanged),
        ]
        for invalid in ('not-json', '[]', '{"fields":{"1":[]}}', '{"manual":[{"kind":"file","target_id":"not-a-uuid"}]}', '{"manual":[{"kind":"object","target_id":"1","content_type_id":1}]}'):
            cases.append(self.scenario(f"Reject malformed picker payload {invalid}", {"object_references": invalid}, status=400))
        return cases

    def delivery_ok(self, _response: HttpResponse) -> bool:
        """Require exactly one delivery for a valid request."""
        self.smtp.send_message.assert_called_once()
        return True

    def delivery_blocked(self, response: HttpResponse) -> bool:
        """Require an actionable error without a partial message or private filename."""
        self.smtp.send_message.assert_not_called()
        self.assertIn("errors", response.json())
        self.assertNotIn("secret.png", response.content.decode())
        if hasattr(self, "read_guard"):
            self.read_guard.assert_not_called()
        return True

    def mixed_mime(self, response: HttpResponse) -> bool:
        """Verify bytes, filenames, content types, CIDs and image positions in the actual wire MIME."""
        self.delivery_ok(response)
        message = self.smtp.send_message.call_args.args[0]
        parts = [part for part in message.walk() if part.get_content_disposition()]
        self.assertEqual({(part.get_filename(), part.get_content_disposition()) for part in parts}, {("original.pdf", "attachment"), ("image.png", "attachment"), ("image.png", "inline"), ("legacy.txt", "attachment")})
        inline = next(part for part in parts if part.get_content_disposition() == "inline")
        self.assertEqual(inline.get_payload(decode=True), self.image_bytes)
        self.assertEqual(inline.get_content_type(), "image/png")
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertEqual(html.count("cid:" + inline["Content-ID"][1:-1]), 2)
        self.assertLess(html.index("Before"), html.index("cid:"))
        self.assertLess(html.index("cid:"), html.index("After"))
        self.assertIn('alt="Diagram"', html)
        self.assertIn("width:120px", html)
        self.assertNotIn("file_id", html)
        self.assertNotIn(str(self.image.pk), html)
        self.assertEqual(next(p for p in parts if p.get_filename() == "original.pdf").get_payload(decode=True), b"original PDF bytes")
        return True

    def inline_mime(self, response: HttpResponse) -> bool:
        """Require an authorized raster inline part without private serving URLs."""
        self.delivery_ok(response)
        message = self.smtp.send_message.call_args.args[0]
        inline = [part for part in message.walk() if part.get_content_disposition() == "inline"]
        self.assertEqual(len(inline), 1)
        self.assertEqual(inline[0].get_payload(decode=True), self.image_bytes)
        self.assertNotIn("/api/files", message.get_body(preferencelist=("html",)).get_content())
        return True

    def grant_picture(self, _scenario: RequestScenario) -> None:
        """Grant only the actual field owning the private image."""
        self.policy = PolicyManager.create_policy(model_or_content_type=self.CustomerModel, global_permissions=["view"], field_permissions={"picture": ["view"]}, row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])])
        self.policy.users.add(self.normal_user)

    def grant_other_field(self, _scenario: RequestScenario) -> None:
        """Grant an unrelated owner field to prove fields remain distinct."""
        policy = PolicyManager.create_policy(model_or_content_type=self.CustomerModel, global_permissions=["view"], field_permissions={"first_name": ["view"]}, row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])])
        policy.users.add(self.normal_user)

    def grant_other_row(self, _scenario: RequestScenario) -> None:
        """Grant the same image field only on an unrelated row."""
        from bloomerp.filters.definition import FilterCondition
        policy = PolicyManager.create_policy(model_or_content_type=self.CustomerModel, global_permissions=["view"], field_permissions={"picture": ["view"]}, row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[FilterCondition(field_path="first_name", lookup_id="equals", value="Different")])])
        policy.users.add(self.normal_user)

    def corrupt_image(self, scenario: RequestScenario) -> None:
        """Corrupt an IDAT checksum that Pillow recognizes but rejects during verification."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from bloomerp.models import FileNode
        content = bytearray(self.image_bytes)
        start = content.index(b"IDAT")
        checksum = start + 4 + int.from_bytes(content[start - 4:start], "big")
        content[checksum] ^= 1
        file = FileNode.objects.create(kind="FILE", created_by=self.normal_user, content=SimpleUploadedFile("corrupt.png", bytes(content)))
        scenario.data["body"] = f'<img data-reference-kind="file" data-target-id="{file.pk}" src="private">'

    def select_folder(self, scenario: RequestScenario) -> None:
        """Forge a valid node ID that identifies a folder rather than file bytes."""
        from bloomerp.models import FileNode
        folder = FileNode.objects.create(kind="FOLDER", name="Folder", created_by=self.normal_user)
        scenario.data["object_references"] = self.selection(folder.pk)

    def revoke_picture(self, scenario: RequestScenario) -> None:
        """Revoke a previously usable selection before posting the message."""
        from bloomerp.files.access import FileAccessManager
        self.grant_picture(scenario)
        self.assertTrue(FileAccessManager(self.normal_user).can_read_file_node(self.private))
        self.policy.users.remove(self.normal_user)

    def forbid_reads(self, _scenario: RequestScenario) -> None:
        """Make any storage read fail so authorization must finish first."""
        from django.db.models.fields.files import FieldFile
        guard = patch.object(FieldFile, "open", side_effect=AssertionError("Read before authorization"))
        self.read_guard = guard.start()
        self.scenario_patches.append(guard)
        self.addCleanup(guard.stop)

    def delete_image(self, scenario: RequestScenario) -> None:
        """Delete the selected file and retain an owned draft for the retry."""
        self.draft = EmailDraft.objects.create(user=self.normal_user, payload={"body": self.body})
        scenario.data["draft_id"] = str(self.draft.pk)
        self.image.delete()

    def failed_draft_retained(self, response: HttpResponse) -> bool:
        """Prove a failed resolution does not remove the sender's saved input."""
        self.delivery_blocked(response)
        return EmailDraft.objects.filter(pk=self.draft.pk, payload__body=self.body).exists()

    def missing_blob(self, _scenario: RequestScenario) -> None:
        """Simulate missing storage without deleting a fixture shared by scenarios."""
        from django.db.models.fields.files import FieldFile
        missing = patch.object(FieldFile, "open", side_effect=FileNotFoundError)
        missing.start()
        self.scenario_patches.append(missing)
        self.addCleanup(missing.stop)

    def small_limit(self, _scenario: RequestScenario) -> None:
        """Use a bounded budget and stale size metadata to exercise actual-byte accounting."""
        from bloomerp.models import FileNode
        FileNode.objects.filter(pk__in=[self.document.pk, self.image.pk]).update(meta={"size": 1})
        limit = patch("bloomerp.services.email_attachment_services.MAX_EMAIL_ATTACHMENT_BYTES", len(self.image_bytes))
        limit.start()
        self.scenario_patches.append(limit)
        self.addCleanup(limit.stop)

    def upload_new(self, scenario: RequestScenario) -> None:
        """Create a file through the shared upload API before combining it with an existing file."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        from bloomerp.models import FileNode
        policy = PolicyManager.create_policy(model_or_content_type=FileNode, global_permissions=["add", "view"], field_permissions={}, row_permissions=[])
        policy.users.add(self.normal_user)
        self.client.force_login(self.normal_user)
        response = self.client.post(reverse("api_assistant_file_upload"), {"file": SimpleUploadedFile("new.txt", b"new upload", content_type="text/plain")})
        self.assertEqual(response.status_code, 201)
        scenario.data["object_references"] = self.selection(self.document.pk, response.json()["file_id"])

    def uploaded_mime(self, response: HttpResponse) -> bool:
        """Require original content from both the shared upload API and stored selection."""
        self.delivery_ok(response)
        parts = list(self.smtp.send_message.call_args.args[0].iter_attachments())
        self.assertEqual({part.get_payload(decode=True) for part in parts}, {b"new upload", b"original PDF bytes"})
        return True

    def removal_preserves_source(self, response: HttpResponse) -> bool:
        """Sending without a removed selection must not delete or reparent any stored file."""
        self.delivery_ok(response)
        self.assertEqual(list(self.smtp.send_message.call_args.args[0].iter_attachments()), [])
        self.private.refresh_from_db()
        self.assertEqual(self.private.references.count(), 1)
        return True

    def external_unchanged(self, response: HttpResponse) -> bool:
        """Preserve an external image link without converting it into a server-side request."""
        self.delivery_ok(response)
        message = self.smtp.send_message.call_args.args[0]
        self.assertEqual(list(message.iter_attachments()), [])
        self.assertIn("https://external.example.test/image.png", message.get_body(preferencelist=("html",)).get_content())
        return True
