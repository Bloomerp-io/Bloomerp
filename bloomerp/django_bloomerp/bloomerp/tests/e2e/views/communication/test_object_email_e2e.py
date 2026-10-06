"""Browser coverage of the shared object email modal and SDK autosave."""

import re
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from playwright.sync_api import Route, expect

from bloomerp.communication.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.models import DocumentTemplate, EmailAccount, EmailDraft, User
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario


class TestObjectEmailE2E(BloomerpE2ETestCase):
    """Prove template copying, rich-text edits, autosave, preview, and sending."""

    auto_create_customers = False

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Open a real detail sidebar and complete a templated email without SMTP."""
        self.normal_user.email = "recipient@example.com"
        self.normal_user.first_name = "Ada"
        self.normal_user.save(update_fields=["email", "first_name"])
        self.account = EmailAccount.objects.create(name="Sender", email_address="sender@example.com")
        self.admin_user.default_email_account = self.account
        self.admin_user.save(update_fields=["default_email_account"])
        self.template = DocumentTemplate.objects.create(
            name="Greeting", template="<p>Hello {{ user.first_name }}</p>",
            free_variables=[{"slug": "note", "label": "Note", "type": "text", "required": True}],
        )
        self.template.content_types.add(
            ContentType.objects.get_for_model(User), ContentType.objects.get_for_model(EmailAccount),
        )
        self.second_template = DocumentTemplate.objects.create(
            name="Closing", template="<p>{{ vars.closing }}: {{ vars.note }}</p>",
            free_variables=[
                {"slug": "closing", "label": "Closing", "type": "text", "required": True},
                {"slug": "note", "label": "Note", "type": "text", "required": True},
            ],
        )
        return [E2ERequestScenario(
            name="Send an edited document template from an object",
            user=self.admin_user, url=self.normal_user.get_absolute_url(),
            prepare=self.mock_delivery, cleanup=self.stop_delivery,
            actions=[
                E2EAction(name="Toggle the detail panel independently", execute=self.toggle_detail_panel),
                E2EAction(name="Open the email field action", execute=self.open_composer),
                E2EAction(name="Use modal shortcuts while typing", execute=self.use_modal_shortcuts),
                E2EAction(name="Edit recipient chips and reject invalid addresses", execute=self.edit_recipients),
                E2EAction(name="Load the template and edit its copy", execute=self.edit_template),
                E2EAction(name="Append another template without losing variables", execute=self.append_template),
                E2EAction(name="Preview the resolved edited email", execute=self.preview_email),
                E2EAction(name="Send the email and remove its draft", execute=self.send_email),
            ],
        )]

    def mock_delivery(self) -> None:
        """Prevent the browser test from contacting an actual SMTP server."""
        self.delivery_patch = patch.object(ImapSmtpAdapter, "send_email", return_value="<browser@example.com>")
        self.delivery_mock = self.delivery_patch.start()

    def stop_delivery(self) -> None:
        """Restore real adapter behavior after the isolated browser scenario."""
        self.delivery_patch.stop()

    def toggle_detail_panel(self) -> None:
        """Close and reopen the detail panel without changing the main sidebar."""
        self.page.set_viewport_size({"width": 1440, "height": 1000})
        panel = self.page.locator("#resizable-div-detail-aside")
        sidebar = self.page.locator("#sidebar")
        original_sidebar_class = sidebar.get_attribute("class")
        original_width = panel.bounding_box()["width"]
        field = self.page.locator("#id_first_name")
        field.press("ControlOrMeta+Shift+y")
        expect(panel).to_have_css("width", "0px")
        self.assertEqual(sidebar.get_attribute("class"), original_sidebar_class)
        field.press("ControlOrMeta+Shift+y")
        expect(panel).not_to_have_css("width", "0px")
        self.assertAlmostEqual(panel.bounding_box()["width"], original_width, delta=1)
        self.assertEqual(sidebar.get_attribute("class"), original_sidebar_class)

    def open_composer(self) -> None:
        """Use the detail action and verify the recipient and preferred sender."""
        self.page.get_by_role("button", name="Email", exact=True).click()
        self.page.locator('[bloomerp-open-modal="detail-email-modal"]').click()
        self.composer = self.page.locator('[bloomerp-component="email-editor"]')
        expect(self.composer.locator('[name="to"]')).to_have_value("recipient@example.com")
        expect(self.composer.locator('[name="email_account_id"]')).to_have_value(str(self.account.pk))

    def use_modal_shortcuts(self) -> None:
        """Toggle fullscreen and close the active composer through documented shortcuts."""
        modal = self.page.locator("#detail-email-modal-container")
        fullscreen = modal.get_by_role("button", name="Toggle fullscreen", exact=True)
        fullscreen.hover()
        expect(modal.locator('[data-shortcut="mod+shift+space"] [data-shortcut-tooltip]')).to_be_visible()
        entry = self.composer.get_by_role("combobox", name="To", exact=True)
        entry.press("ControlOrMeta+Shift+Space")
        expect(modal).to_have_class(re.compile(r".*\bmax-w-full\b.*"))
        entry.press("ControlOrMeta+Shift+Space")
        expect(modal).to_have_class(re.compile(r".*\bmax-w-6xl\b.*"))
        entry.press("ControlOrMeta+Shift+Comma")
        expect(modal).to_be_hidden()
        self.page.get_by_role("button", name="Email", exact=True).click()
        self.page.locator('[bloomerp-open-modal="detail-email-modal"]').click()
        expect(modal).to_be_visible()
        expect(self.composer.get_by_role("combobox", name="To", exact=True)).to_be_visible()

    def hold_recipient_search(self, route: Route) -> None:
        """Keep one suggestion request pending to verify its visible loading state."""
        self.pending_recipient_search = route

    def edit_recipients(self) -> None:
        """Exercise pasted lists, chip removal, keyboard editing, and validation."""
        expect(self.composer.locator('[data-template-panel]')).to_have_count(0)
        expect(self.composer.locator('[data-recipient-chip="recipient@example.com"]')).to_be_visible()
        entry = self.composer.get_by_role("combobox", name="To", exact=True)
        entry.fill("sender")
        option = self.composer.get_by_role("listbox").get_by_role("option", name="sender@example.com", exact=False)
        expect(option).to_be_visible()
        group = self.composer.get_by_role("listbox").get_by_role("group", name="Email Account", exact=True)
        expect(group).to_be_visible()
        expect(group.get_by_role("option")).to_have_text("sender@example.com")
        search_pattern = "**/components/communication/emails/search_email_address/**"
        self.page.route(search_pattern, self.hold_recipient_search)
        with self.page.expect_request(search_pattern):
            entry.fill("sender@")
        suggestions = self.composer.get_by_role("listbox")
        expect(suggestions).to_be_visible()
        expect(suggestions).to_have_attribute("aria-busy", "true")
        expect(suggestions.get_by_role("status")).to_contain_text("Searching email addresses")
        entry.press("ArrowDown")
        self.assertIsNone(entry.get_attribute("aria-activedescendant"))
        self.pending_recipient_search.fulfill(json={"suggestions": [
            {"email": "sender@example.com", "label": "Email Account"},
        ]})
        self.page.unroute(search_pattern, self.hold_recipient_search)
        expect(option).to_be_visible()
        expect(suggestions).not_to_have_attribute("aria-busy", "true")
        entry.press("ArrowDown")
        entry.press("Enter")
        expect(self.composer.locator('[data-recipient-chip="sender@example.com"]')).to_be_visible()
        self.composer.get_by_role("button", name="Remove recipient: sender@example.com", exact=True).click()
        entry.fill("sender@example.com")
        expect(option).to_be_visible()
        entry.press("Escape")
        expect(option).to_have_count(0)
        expect(entry).to_have_value("sender@example.com")
        entry.fill("Second <second@example.com>; third@example.com")
        expect(self.composer.locator('[name="to"]')).to_have_value("recipient@example.com, Second <second@example.com>, third@example.com")
        self.composer.get_by_role("button", name="Remove recipient: Second <second@example.com>", exact=True).click()
        entry.press("Backspace")
        expect(entry).to_have_value("third@example.com")
        entry.fill("updated@example.com")
        entry.press("Enter")
        self.composer.locator('[data-show-cc]').click()
        cc = self.composer.get_by_role("combobox", name="Cc", exact=True)
        cc.fill("team@example.com")
        cc.press("Tab")
        self.composer.locator('[data-show-bcc]').click()
        bcc = self.composer.get_by_role("combobox", name="Bcc", exact=True)
        bcc.fill("invalid-address")
        bcc.press("Enter")
        self.composer.get_by_role("button", name="Send", exact=True).click()
        self.delivery_mock.assert_not_called()
        expect(bcc).to_be_focused()
        self.composer.get_by_role("button", name="Remove recipient: invalid-address", exact=True).click()
        expect(self.composer.locator('[name="bcc"]')).to_have_value("")

    def edit_template(self) -> None:
        """Change copied placeholders and wait for a persisted SDK draft snapshot."""
        self.composer.get_by_role("button", name="Show formatting toolbar").click()
        self.composer.get_by_role("button", name="Template", exact=True).click()
        picker = self.page.get_by_role("group", name="Template", exact=True)
        picker.get_by_role("searchbox", name="Search templates").fill("Greeting")
        with self.page.expect_response("**/components/communication/emails/template/") as loaded:
            picker.get_by_role("button", name="Greeting", exact=True).click()
        self.assertEqual(loaded.value.json()["body"], self.template.template)
        root_widget = self.composer.locator('[data-field-name="template_args-emailaccount"]')
        root_widget.locator('input[type="text"]').fill("sender")
        self.page.locator(f'.foreign-field-results li[data-id="{self.account.pk}"]').click()
        expect(self.composer.locator('[name="template_args-emailaccount"]')).to_have_value(str(self.account.pk))
        editor = self.composer.locator('[contenteditable]')
        expect(editor).to_contain_text("Hello {{ user.first_name }}")
        self.composer.locator('[name="subject"]').fill("Personal greeting")
        self.composer.locator('[name="template_args-note"]').fill("Welcome")
        self.composer.locator('[name="attachments"]').set_input_files({
            "name": "note.txt", "mimeType": "text/plain", "buffer": b"draft file",
        })
        editor.fill("Edited {{ user.first_name }}: {{ vars.note }}")
        expect(self.composer.locator('[data-email-status]')).to_have_text("Draft saved.")
        draft = EmailDraft.objects.get(user=self.admin_user)
        self.assertIn("Edited {{ user.first_name }}", draft.payload["body"])
        self.assertEqual(draft.payload["to"], "recipient@example.com, updated@example.com")
        self.assertEqual(draft.payload["cc"], "team@example.com")
        self.assertEqual(draft.payload["attachments"][0]["content_base64"], "ZHJhZnQgZmlsZQ==")
        self.template.refresh_from_db()
        self.assertEqual(self.template.template, "<p>Hello {{ user.first_name }}</p>")

    def append_template(self) -> None:
        """Preserve populated widgets and shared variables while adding another template."""
        editor = self.composer.locator("[contenteditable]")
        editor.press("ControlOrMeta+End")
        self.composer.get_by_role("button", name="Template", exact=True).click()
        picker = self.page.get_by_role("group", name="Template", exact=True)
        picker.get_by_role("searchbox", name="Search templates").fill("Closing")
        picker.get_by_role("button", name="Closing", exact=True).click()
        note = self.composer.locator('[name="template_args-note"]')
        expect(note).to_have_count(1)
        expect(note).to_have_value("Welcome")
        expect(self.composer.locator('[name="template_args-emailaccount"]')).to_have_value(str(self.account.pk))
        self.composer.locator('[name="template_args-closing"]').fill("Goodbye")
        expect(self.composer.locator('[data-email-status]')).to_have_text("Draft saved.")
        draft = EmailDraft.objects.get(user=self.admin_user)
        self.assertEqual(draft.payload["document_template_ids"], [str(self.template.pk), str(self.second_template.pk)])
        self.assertEqual(draft.payload["arguments"]["template_args-note"], ["Welcome"])

    def preview_email(self) -> None:
        """Verify preview renders the edited copy and typed free variable."""
        self.composer.get_by_role("button", name="Preview", exact=True).click()
        expect(self.composer.frame_locator("iframe").get_by_text("Edited Ada: Welcome")).to_be_visible()
        expect(self.composer.frame_locator("iframe").get_by_text("Goodbye: Welcome")).to_be_visible()

    def send_email(self) -> None:
        """Confirm the same editor sends once and removes the successful draft."""
        self.composer.get_by_role("button", name="Send", exact=True).click()
        expect(self.composer.get_by_text("Email sent successfully.")).to_be_visible()
        self.delivery_mock.assert_called_once()
        self.assertEqual(self.delivery_mock.call_args.kwargs["to"], ["recipient@example.com", "updated@example.com"])
        self.assertEqual(self.delivery_mock.call_args.kwargs["cc"], ["team@example.com"])
        self.assertIn("Edited Ada: Welcome", self.delivery_mock.call_args.kwargs["body_html"])
        self.assertIn("Goodbye: Welcome", self.delivery_mock.call_args.kwargs["body_html"])
        self.assertFalse(EmailDraft.objects.filter(user=self.admin_user).exists())
