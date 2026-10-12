"""Shared conversation fixtures for generated IM model scenarios."""

from functools import partial
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from bloomerp.models.communication.instant_messaging import (
    IMConnection,
    IMConversation,
    IMConversationParticipant,
    IMEndpoint,
    IMIdentity,
    IMMessage,
)
from bloomerp.tests.base import ExpectedModelException, ModelScenario


class IMFixtures:
    """Prepare isolated conversation graphs inside the scenario transaction."""

    def prepare(self) -> None:
        """Create two conversations, staff participants and separate root messages."""
        self.connection = None
        self.external = IMConnection.objects.create(
            name="WhatsApp", provider="whatsapp"
        )
        self.endpoint = IMEndpoint.objects.create(
            connection=self.external, external_id="phone", name="Sales"
        )
        self.user = get_user_model().objects.create_user(username="im-test-user")
        self.other_user = get_user_model().objects.create_user(username="im-test-other")
        self.conversation = IMConversation.objects.create(
            connection=self.connection, kind="group"
        )
        self.other = IMConversation.objects.create(connection=self.connection)
        self.participant = IMConversationParticipant.objects.create(
            conversation=self.conversation, user=self.user
        )
        self.other_participant = IMConversationParticipant.objects.create(
            conversation=self.other, user=self.other_user
        )
        self.root = IMMessage.objects.create(
            conversation=self.conversation,
            sender=self.participant,
            sequence=1,
            body="Root",
        )
        self.reply = IMMessage.objects.create(
            conversation=self.conversation,
            sender=self.participant,
            sequence=2,
            body="Reply",
            thread_root=self.root,
        )
        self.foreign = IMMessage.objects.create(
            conversation=self.other,
            sender=self.other_participant,
            sequence=1,
            body="Other",
        )
        self.identity = IMIdentity.objects.create(
            connection=self.external, external_id="remote-user", address="+32470000001"
        )

    def args(self, model_kind: str, **overrides: Any) -> dict[str, Any]:
        """Build model arguments after scenario fixtures have been prepared."""
        values = {
            "message": {
                "conversation": self.conversation,
                "sender": self.participant,
                "sequence": 3,
                "body": "Hello",
            },
            "reaction": {
                "message": self.root,
                "participant": self.participant,
                "emoji": "👍🏽",
            },
            "participant": {"conversation": self.conversation, "user": self.other_user},
            "read": {
                "participant": self.participant,
                "thread_root": self.root,
                "last_read_message": self.reply,
            },
            "conversation": {"connection": self.connection},
            "identity": {"connection": self.external, "external_id": "new-identity"},
            "endpoint": {
                "connection": self.external,
                "external_id": "another-phone",
                "name": "Support",
            },
            "authorization": {"connection": self.external},
        }[model_kind]
        values.update(overrides)
        return values

    def foreign_args(self, kind: str, field: str, fixture: str) -> dict[str, Any]:
        """Substitute one related fixture to exercise cross-conversation validation."""
        return self.args(kind, **{field: getattr(self, fixture)})

    def scenario(
        self, name: str, model_kind: str, *, invalid: bool = False, **kwargs: Any
    ) -> ModelScenario:
        """Build a prepared lifecycle scenario and optional validation failure."""
        return ModelScenario(
            name=name,
            preparation=self.prepare,
            create_args=partial(self.args, model_kind, **kwargs),
            expected_exceptions=[ExpectedModelException("create", ValidationError)]
            if invalid
            else [],
        )

    def invalid_relation(self, kind: str, field: str, fixture: str) -> ModelScenario:
        """Describe rejection of a foreign record at the model save boundary."""
        return ModelScenario(
            name=f"Reject {kind} with foreign {field}",
            preparation=self.prepare,
            create_args=partial(self.foreign_args, kind, field, fixture),
            expected_exceptions=[ExpectedModelException("create", ValidationError)],
        )
