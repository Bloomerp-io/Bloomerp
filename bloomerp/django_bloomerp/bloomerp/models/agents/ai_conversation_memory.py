"""Private reusable facts produced by MCP endpoint memory policies."""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from .base import AgentModel
from .fields import AgentJSONField


class AIConversationMemory(AgentModel):
    """Store one versioned fact per conversation, tool and endpoint-defined key."""

    conversation = models.ForeignKey(
        "bloomerp.AIConversation", on_delete=models.CASCADE, related_name="memories"
    )
    tool_identifier = models.CharField(max_length=255)
    key = models.CharField(max_length=255)
    payload = AgentJSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    source_tool_call = models.ForeignKey(
        "bloomerp.AIToolCall", on_delete=models.CASCADE, related_name="memories"
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_conversation_memory"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["conversation", "tool_identifier", "key"],
                name="ai_memory_conversation_tool_key",
            ),
        ]

    def clean(self) -> None:
        """Keep provenance inside the owning conversation and producing tool."""
        super().clean()
        if self.source_tool_call_id:
            source = self.source_tool_call
            self.check_conversation(
                "source_tool_call", source.run.conversation_id, self.conversation_id
            )
            if (
                source.tool_identifier != self.tool_identifier
                or source.status != "completed"
            ):
                raise ValidationError(
                    {
                        "source_tool_call": "Memory requires a successful call to its producing tool."
                    }
                )
        if self.version < 1:
            raise ValidationError({"version": "Memory versions must be positive."})
