"""Provider-independent conversation messages."""

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from bloomerp.filters.definition import FilterCondition
from bloomerp.lookups import builtins as lookups
from bloomerp.models.definition import ApiAccessSettings, ApiSettings
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent

from .base import AgentModel
from .fields import AgentJSONField


class AIMessage(AgentModel):
    """Store one ordered transcript entry, optionally produced by a run."""

    bloomerp_config = AgentModel.bloomerp_config.model_copy(
        deep=True,
        update={
            "api_settings": ApiSettings(
                enable_auto_generation=True,
                access=ApiAccessSettings(
                    authenticated=[
                        AccessRule(
                            row_permissions=[
                                RowPolicyRuleContent(
                                    permissions=["view", "add"],
                                    conditions=[
                                        FilterCondition(
                                            field_path="conversation__owner__pk",
                                            lookup_id=lookups.EQUALS.id,
                                            value="$user",
                                        )
                                    ],
                                )
                            ],
                            field_permissions={
                                "id": ["view", "add"],
                                "conversation": ["view", "add"],
                                "content_blocks": ["view", "add"],
                                "sequence": ["view"],
                                "role": ["view"],
                                "status": ["view"],
                                "run": ["view"],
                                "datetime_created": ["view"],
                            },
                        )
                    ],
                ),
            )
        },
    )

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_message"
        ordering: ClassVar[list[str]] = ["sequence"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"], name="ai_message_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1), name="ai_message_sequence_positive"
            ),
        ]

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    immutable_fields = ("conversation_id", "run_id", "sequence")
    conversation = models.ForeignKey(
        "bloomerp.AIConversation", on_delete=models.CASCADE, related_name="messages"
    )
    run = models.ForeignKey(
        "bloomerp.AIRun",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="messages",
    )
    sequence = models.PositiveBigIntegerField()
    role = models.CharField(max_length=16, choices=Role.choices)
    content_blocks = AgentJSONField(schema="message.v1", default=list, blank=True)
    status = models.CharField(
        max_length=16,
        default="completed",
        choices=[
            ("streaming", "Streaming"),
            ("completed", "Completed"),
            ("interrupted", "Interrupted"),
        ],
    )
    schema_version = models.PositiveIntegerField(default=1, choices=[(1, "Version 1")])

    def clean(self) -> None:
        """Prevent a message from referencing a run in another conversation."""
        super().clean()
        if self.run_id:
            self.check_conversation(
                "run", self.run.conversation_id, self.conversation_id
            )
        for block in self.content_blocks:
            if block["type"] == "approval":
                from .ai_approval import AIApproval

                approval = (
                    AIApproval.objects.filter(pk=block["approval_id"])
                    .select_related("tool_call__run")
                    .first()
                )
                if approval is None:
                    from django.core.exceptions import ValidationError

                    raise ValidationError(
                        {"content_blocks": "Referenced approval does not exist."}
                    )
                self.check_conversation(
                    "content_blocks",
                    approval.tool_call.run.conversation_id,
                    self.conversation_id,
                )

    def attachment_specs(self) -> list[dict[str, Any]]:
        """Return canonical attachment metadata for client-message retry comparison."""
        return [
            {
                "kind": link.artifact.kind,
                "schema_version": link.artifact.schema_version,
                "payload": link.artifact.payload,
                "file_id": link.artifact.file_id,
            }
            for link in self.artifact_links.select_related("artifact").order_by(
                "position"
            )
        ]

    def attach_artifacts(self, selections: list[dict[str, Any]]) -> None:
        """Append selected artifacts and their ordered blocks atomically under the conversation lock."""
        from uuid import uuid5

        from django.db import transaction

        from .ai_artifact import AIArtifact
        from .ai_conversation import AIConversation
        from .ai_message_artifact import AIMessageArtifact

        if not selections:
            return
        with transaction.atomic():
            AIConversation.objects.select_for_update().get(pk=self.conversation_id)
            if self.artifact_links.exists():
                if self.attachment_specs() != selections:
                    raise ValidationError("Attachments conflict with existing message")
                return
            self.refresh_from_db()
            for position, selection in enumerate(selections):
                artifact = AIArtifact.objects.create(
                    id=uuid5(self.pk, f"attachment:{position}"),
                    conversation_id=self.conversation_id,
                    created_by_message=self,
                    **selection,
                )
                AIMessageArtifact.objects.create(
                    message=self, artifact=artifact, position=position
                )
                self.content_blocks.append({"type": "artifact", "position": position})
            self.save()
