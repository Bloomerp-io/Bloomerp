"""Default owner-scoped transcript reads through unmodified generated APIs."""

from typing import Any
from uuid import uuid4

from bloomerp.models import User
from bloomerp.models.agents import AIConversation, AIMessage
from bloomerp.tests.base import (
    BloomerpAPIDetailViewTestCase,
    BloomerpAPIModelViewTestCase,
    ExpectedResult,
    RequestScenario,
)
from django.db.models import Model
from django.http import HttpResponse


class TranscriptFixtures:
    """Seed two owners without granting agent use or stored transcript policies."""

    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Create owned/foreign transcripts and a hidden system message."""
        self.normal_user.is_staff = False
        self.normal_user.save(update_fields=["is_staff"])
        self.other = User.objects.create_user(username="other-api-transcript-owner")
        self.inactive = User.objects.create_user(
            username="inactive-api-owner", is_active=False
        )
        self.own_conversation = AIConversation.objects.create(owner=self.normal_user)
        self.foreign_conversation = AIConversation.objects.create(owner=self.other)
        self.own_message = self.own_conversation.append_message(
            content=[{"type": "text", "text": "Hello"}], role="user", message_id=uuid4()
        )
        self.system_message = self.own_conversation.append_message(
            content=[{"type": "text", "text": "Private system context"}],
            role="system",
            message_id=uuid4(),
        )
        self.foreign_message = self.foreign_conversation.append_message(
            content=[{"type": "text", "text": "Another owner's text"}],
            role="user",
            message_id=uuid4(),
        )
        self.own_conversation.refresh_from_db()
        self.owned = (
            self.own_conversation if self.model is AIConversation else self.own_message
        )
        self.foreign = (
            self.foreign_conversation
            if self.model is AIConversation
            else self.foreign_message
        )

    def expected_row(self) -> dict[str, Any]:
        """Describe the safe metadata/content exposed by the default view grant."""
        row = self.owned
        result = {
            "id": str(row.pk),
            "status": row.status,
            "datetime_created": row.datetime_created.isoformat().replace("+00:00", "Z"),
        }
        if self.model is AIConversation:
            result.update(
                title=row.title,
                selected_agent=None,
                datetime_updated=row.datetime_updated.isoformat().replace(
                    "+00:00", "Z"
                ),
            )
        else:
            result.update(
                conversation=str(row.conversation_id),
                content_blocks=row.content_blocks,
                sequence=row.sequence,
                role=row.role,
                run=None,
            )
        return result

    def only_owned_row(self, response: HttpResponse) -> bool:
        """Compare the list payload exactly, including its default field restrictions."""
        data = response.json()
        rows = data.get("results", []) if isinstance(data, dict) else data
        return rows == [self.expected_row()]

    def owned_detail(self, response: HttpResponse) -> bool:
        """Return safe fields for exactly the requested owned transcript record."""
        return response.json() == self.expected_row()


class TranscriptListScenarios(TranscriptFixtures):
    """Share collection scenarios across the two generated transcript resources."""

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Allow authenticated owner reads while denying anonymous access and creates."""
        return [
            RequestScenario(
                name="Non-staff owner fetches only their safe transcript fields",
                user=self.normal_user,
                expected=ExpectedResult(response_validators=self.only_owned_row),
            ),
            RequestScenario(
                name="Anonymous denied", expected=ExpectedResult(status_code=401)
            ),
            RequestScenario(
                name="Inactive account denied",
                user=self.inactive,
                expected=ExpectedResult(status_code=401),
            ),
            RequestScenario(
                name="Default view grant cannot create records",
                user=self.normal_user,
                method="POST",
                content_type="application/json",
                data={"id": str(uuid4())},
                expected=ExpectedResult(status_code=403),
            ),
        ]


class TranscriptDetailScenarios(TranscriptFixtures):
    """Share detail and mutation-denial scenarios across private transcripts."""

    def create_test_object(self) -> Model:
        """Use the seeded owner record as the default detail-route object."""
        return self.owned

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Allow owned detail reads and deny foreign reads and all default mutations."""
        scenarios = [
            RequestScenario(
                name="Owner reads a transcript record",
                user=self.normal_user,
                expected=ExpectedResult(response_validators=self.owned_detail),
            ),
            RequestScenario(
                name="Other owner's record is hidden",
                user=self.normal_user,
                view_kwargs={"pk": self.foreign.pk},
                expected=ExpectedResult(status_code=404),
            ),
        ]
        scenarios.extend(
            RequestScenario(
                name=f"Default view grant denies {method}",
                user=self.normal_user,
                method=method,
                content_type="application/json",
                data={},
                expected=ExpectedResult(status_code=404),
            )
            for method in ("PUT", "PATCH", "DELETE")
        )
        if self.model is AIMessage:
            scenarios.append(
                RequestScenario(
                    name="System messages remain hidden",
                    user=self.normal_user,
                    view_kwargs={"pk": self.system_message.pk},
                    expected=ExpectedResult(status_code=404),
                )
            )
        return scenarios


class TestConversationListAPI(TranscriptListScenarios, BloomerpAPIModelViewTestCase):
    """Fetch owned conversation collections using model-configured view access."""

    model = AIConversation
    view_name = "ai_conversations-list"


class TestMessageListAPI(TranscriptListScenarios, BloomerpAPIModelViewTestCase):
    """Fetch user/assistant message collections through the generated API."""

    model = AIMessage
    view_name = "ai_messages-list"


class TestConversationDetailAPI(
    TranscriptDetailScenarios, BloomerpAPIDetailViewTestCase
):
    """Fetch owned conversation details without adding mutation grants."""

    model = AIConversation
    view_name = "ai_conversations-detail"


class TestMessageDetailAPI(TranscriptDetailScenarios, BloomerpAPIDetailViewTestCase):
    """Fetch owned message details while denying system and foreign messages."""

    model = AIMessage
    view_name = "ai_messages-detail"
