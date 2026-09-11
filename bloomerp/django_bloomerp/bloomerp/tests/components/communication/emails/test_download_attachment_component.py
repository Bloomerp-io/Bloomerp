from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory

from bloomerp.communication.emails.actions import (
    _upsert_email_inbox_item_result,
    render_email,
)
from bloomerp.communication.emails.base_adapter import (
    BloomerpEmail,
    EmailAttachment,
    EmailAttachmentMetadata,
)
from bloomerp.communication.inbox_folder_definition import InboxFolderType
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class EmailAttachmentFixtureMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="attachment-owner",
            email="attachment-owner@example.com",
            password="password",
        )
        self.other_user = get_user_model().objects.create_user(
            username="attachment-outsider",
            email="attachment-outsider@example.com",
            password="password",
        )
        inbox = Inbox.objects.create(user=self.user, name="Email inbox")
        self.email_account = EmailAccount.objects.create(
            email_address="attachments@example.com",
        )
        self.folder = InboxFolder.objects.create(
            inbox=inbox,
            type=InboxFolderType.EMAIL.value.key,
            related_object_id=str(self.email_account.pk),
        )
        self.item = InboxItem.objects.create(
            folder=self.folder,
            item_type=InboxFolderType.EMAIL.value.item_type.key,
            related_item_id="message-42",
            title="Contract",
            raw_meta_data={
                "email_account_id": str(self.email_account.pk),
                "provider_message_id": "42",
                "mailbox": "INBOX",
                "attachments": [
                    {
                        "id": "2",
                        "filename": "contract.pdf",
                        "content_type": "application/pdf",
                        "size": 2048,
                    }
                ],
            },
        )


class TestDownloadAttachmentComponent(
    EmailAttachmentFixtureMixin,
    BloomerpComponentTestCase,
):
    """Tests secured attachment downloads through the component endpoint."""

    view_name = "components_emails_download_attachment"

    def get_test_scenarios(self) -> list[RequestScenario]:
        view_kwargs = {
            "inbox_item_id": self.item.pk,
            "attachment_id": "2",
        }
        return [
            RequestScenario(
                name="inbox owner downloads attachment",
                user=self.user,
                view_kwargs=view_kwargs,
                prepare=self._prepare_attachment,
                expected=ExpectedResult(
                    response_validators=self._valid_attachment_response,
                ),
            ),
            RequestScenario(
                name="hide attachment from user outside inbox",
                user=self.other_user,
                view_kwargs=view_kwargs,
                prepare=self._watch_attachment_fetch,
                expected=ExpectedResult(
                    status_code=404,
                    response_validators=self._attachment_was_not_fetched,
                ),
            ),
        ]

    def _start_fetch_patch(self, **kwargs):
        fetch_patch = patch(
            "bloomerp.components.communication.emails.download_attachment."
            "fetch_email_attachment",
            **kwargs,
        )
        mocked_fetch = fetch_patch.start()
        self.addCleanup(fetch_patch.stop)
        self._fetch_attachment_mock = mocked_fetch

    def _prepare_attachment(self, _setup: RequestScenario) -> None:
        self._start_fetch_patch(
            return_value=EmailAttachment(
                filename="contract.pdf",
                content=b"contract content",
                content_type="application/pdf",
            )
        )

    def _watch_attachment_fetch(self, _setup: RequestScenario) -> None:
        self._start_fetch_patch()

    def _valid_attachment_response(self, response) -> bool:
        return (
            b"".join(response.streaming_content) == b"contract content"
            and response["Content-Type"] == "application/pdf"
            and "contract.pdf" in response["Content-Disposition"]
            and response["X-Content-Type-Options"] == "nosniff"
        )

    def _attachment_was_not_fetched(self, _response) -> bool:
        return not self._fetch_attachment_mock.called


class TestEmailAttachmentPresentation(
    EmailAttachmentFixtureMixin,
    BaseBloomerpTestCaseWithModels,
):
    """Tests persistence and rendering behavior outside the download endpoint."""

    def test_email_upsert_persists_attachment_metadata(self):
        email = BloomerpEmail(
            provider="imap",
            provider_message_id="43",
            email_account_id=str(self.email_account.pk),
            subject="Invoice",
            attachments=[
                EmailAttachmentMetadata(
                    id="2",
                    filename="invoice.pdf",
                    content_type="application/pdf",
                    size=4096,
                )
            ],
        )

        item, created = _upsert_email_inbox_item_result(email, self.folder)

        self.assertTrue(created)
        self.assertEqual(
            item.raw_meta_data["attachments"],
            [
                {
                    "id": "2",
                    "filename": "invoice.pdf",
                    "content_type": "application/pdf",
                    "size": 4096,
                }
            ],
        )

    @patch(
        "bloomerp.communication.emails.actions._resolve_email_adapter_for_account"
    )
    def test_render_email_uses_stored_attachment_metadata(self, resolve_adapter):
        resolve_adapter.return_value.fetch_email_content.return_value = (
            "<p>Email body</p>"
        )
        request = RequestFactory().get("/inbox/")

        html = render_email(self.item, request)

        self.assertIn("contract.pdf", html)
        self.assertIn("2.0\xa0KB", html)
        self.assertIn("components/communication/emails/download_attachment", html)
        self.assertIn("rounded-xl border border-gray-200", html)
        self.assertIn("<iframe", html)
        self.assertIn('sandbox="allow-popups allow-popups-to-escape-sandbox"', html)
        self.assertNotIn("<style>", html)
