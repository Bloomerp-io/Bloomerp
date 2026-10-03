"""Ordered attachment references without duplicating artifact content."""

from typing import ClassVar

from django.db import models

from .base import AgentModel


class AIMessageArtifact(AgentModel):
    """Attach a particular immutable artifact revision to a message position."""
    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_message_artifact"
        ordering: ClassVar[list[str]] = ["position"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["message", "position"], name="ai_message_artifact_position"
            )
        ]
    
    immutable_fields = ("message_id", "artifact_id", "position")
    message = models.ForeignKey(
        "bloomerp.AIMessage", on_delete=models.CASCADE, related_name="artifact_links"
    )
    artifact = models.ForeignKey(
        "bloomerp.AIArtifact", on_delete=models.RESTRICT, related_name="message_links"
    )
    position = models.PositiveIntegerField()
    
    def clean(self) -> None:
        """Keep attachment references inside their message's conversation."""
        super().clean()
        if self.message_id and self.artifact_id:
            self.check_conversation(
                "artifact", self.artifact.conversation_id, self.message.conversation_id
            )
