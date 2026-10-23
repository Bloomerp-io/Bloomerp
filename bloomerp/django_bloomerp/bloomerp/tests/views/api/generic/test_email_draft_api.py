"""Ownership contracts for generated email draft endpoints."""

from django.http import HttpResponse

from bloomerp.models import EmailDraft
from bloomerp.tests.base import (
    BloomerpAPIDetailViewTestCase,
    BloomerpAPIModelViewTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestEmailDraftApi(BloomerpAPIModelViewTestCase):
    """Exercise draft persistence through standard generated model routes."""

    view_name = "email_drafts-list"
    model = EmailDraft
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Verify incomplete snapshots and server-enforced ownership."""
        self.owned = EmailDraft.objects.create(user=self.normal_user, payload={"body": "old"})
        self.foreign = EmailDraft.objects.create(user=self.admin_user, payload={"body": "private"})
        self.snapshot = {
            "to": "unfinished@", "body": "<p>Edited</p>",
            "document_template_ids": ["first", "second"],
            "arguments": {"template_args-note": ["Welcome"]},
            "attachments": [{"filename": "note.txt", "content_type": "text/plain", "content_base64": "ZHJhZnQgZmlsZQ=="}],
        }
        return [
            RequestScenario(
                name="Create incomplete snapshot for current user",
                method="POST", user=self.normal_user, content_type="application/json",
                data={"user": self.normal_user.pk, "payload": self.snapshot},
                expected=ExpectedResult(status_code=201, response_validators=self.saved_snapshot),
            ),
            RequestScenario(
                name="Cannot create a draft for another user",
                method="POST", user=self.normal_user, content_type="application/json",
                data={"user": self.admin_user.pk, "payload": self.snapshot},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Anonymous draft creation is rejected",
                method="POST", content_type="application/json",
                data={"user": self.normal_user.pk, "payload": self.snapshot},
                expected=ExpectedResult(status_code=401),
            ),
        ]

    def saved_snapshot(self, response: HttpResponse) -> bool:
        """Confirm the generated create response identifies the saved owner snapshot."""
        draft = EmailDraft.objects.get(pk=response.json()["id"])
        return draft.user_id == self.normal_user.pk and draft.payload == self.snapshot

class TestEmailDraftDetailApi(BloomerpAPIDetailViewTestCase):
    """Verify updates and reads respect draft ownership."""

    view_name = "email_drafts-detail"
    model = EmailDraft
    auto_create_customers = False

    def create_test_object(self) -> EmailDraft:
        """Provide an owned draft for the generated detail route."""
        return EmailDraft.objects.create(user=self.normal_user, payload={"body": "old"})

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise permitted edits and attempts to cross ownership boundaries."""
        self.owned = self.create_test_object()
        self.foreign = EmailDraft.objects.create(user=self.admin_user, payload={"body": "private"})
        self.snapshot = {"body": "updated"}
        return [
            RequestScenario(
                name="Update own snapshot without creating a duplicate",
                view_name="email_drafts-detail", view_kwargs={"pk": self.owned.pk},
                method="PATCH", user=self.normal_user, content_type="application/json",
                data={"payload": self.snapshot},
                expected=ExpectedResult(response_validators=self.updated_snapshot),
            ),
            RequestScenario(
                name="Cannot change draft ownership",
                view_name="email_drafts-detail", view_kwargs={"pk": self.owned.pk},
                method="PATCH", user=self.normal_user, content_type="application/json",
                data={"user": self.admin_user.pk},
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Autosave preserves server-owned pending delivery state",
                view_kwargs={"pk": self.owned.pk}, method="PATCH", user=self.normal_user,
                content_type="application/json", data={"payload": self.snapshot},
                prepare=self.prepare_pending_send,
                expected=ExpectedResult(response_validators=self.pending_send_is_preserved),
            ),
            RequestScenario(
                name="Draft owner cannot clear pending delivery through the generated API",
                view_kwargs={"pk": self.owned.pk}, method="PATCH", user=self.normal_user,
                content_type="application/json", data={"pending_send": {}},
                prepare=self.prepare_pending_send,
                expected=ExpectedResult(status_code=403, response_validators=self.pending_send_is_preserved),
            ),
            RequestScenario(
                name="Cannot update another user's draft",
                view_name="email_drafts-detail", view_kwargs={"pk": self.foreign.pk},
                method="PATCH", user=self.normal_user, content_type="application/json",
                data={"payload": self.snapshot},
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Cannot read another user's draft",
                view_name="email_drafts-detail", view_kwargs={"pk": self.foreign.pk},
                user=self.normal_user, expected=ExpectedResult(status_code=404),
            ),
        ]

    def updated_snapshot(self, _response: HttpResponse) -> bool:
        """Confirm updating keeps the same row and preserves other owners' data."""
        self.owned.refresh_from_db()
        self.foreign.refresh_from_db()
        return self.owned.payload == self.snapshot and self.foreign.payload == {"body": "private"}

    def prepare_pending_send(self, _scenario: RequestScenario) -> None:
        """Persist an uncertain send reference outside the editable composer payload."""
        self.owned.pending_send = {"provider_message_id": "pending-id", "provider_message_id_scope": "account"}
        self.owned.save(update_fields=["pending_send"])

    def pending_send_is_preserved(self, _response: HttpResponse) -> bool:
        """Ensure editing or attempting to forge a snapshot cannot reset its send guard."""
        self.owned.refresh_from_db()
        return self.owned.pending_send.get("provider_message_id") == "pending-id"
