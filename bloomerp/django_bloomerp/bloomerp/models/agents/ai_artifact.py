"""Immutable structured conversation items and their content revisions."""

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from uuid import UUID

    from django.contrib.auth.base_user import AbstractBaseUser
    from django.http import HttpRequest

    from .ai_tool_call import AIToolCall

from django.core.exceptions import ValidationError
from django.db import models

from .base import AgentModel
from .fields import AgentJSONField


class AIArtifact(AgentModel):
    """Store one immutable file, analytics configuration, or form-patch revision."""

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_artifact"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(previous_revision=models.F("id")),
                name="ai_artifact_not_own_revision",
            )
        ]

    class Kind(models.TextChoices):
        FILE = "file", "File"
        ANALYTICS = "analytics", "Analytics"
        FORM_PATCH = "form_patch", "Form patch"

    immutable_fields = (
        "conversation_id",
        "created_by_message_id",
        "created_by_tool_call_id",
        "previous_revision_id",
        "file_id",
        "kind",
        "schema_version",
        "payload",
    )
    conversation = models.ForeignKey(
        "bloomerp.AIConversation", on_delete=models.CASCADE, related_name="artifacts"
    )
    created_by_message = models.ForeignKey(
        "bloomerp.AIMessage",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="created_artifacts",
    )
    created_by_tool_call = models.ForeignKey(
        "bloomerp.AIToolCall",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="created_artifacts",
    )
    previous_revision = models.ForeignKey(
        "self",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="revisions",
    )
    file = models.ForeignKey(
        "bloomerp.File",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="ai_artifacts",
    )
    kind = models.CharField(max_length=100)
    schema_version = models.PositiveIntegerField(default=1)
    payload = AgentJSONField(schema="object.v1")

    def clean(self) -> None:
        """Validate artifact kind, revision ancestry, and all provenance links."""
        super().clean()
        from bloomerp.agents.artifacts.registry import AI_ARTIFACT_REGISTRY
        from bloomerp.agents.definition import ArtifactPayload

        legacy = self.payload.get("kind") in self.Kind.values
        try:
            if legacy:
                if self.schema_version != 1:
                    raise ValueError("Unsupported legacy artifact schema version")
                self.payload = ArtifactPayload.model_validate(self.payload).model_dump(
                    mode="json"
                )
            else:
                self.payload = AI_ARTIFACT_REGISTRY.validate_payload(
                    self.kind, self.schema_version, self.payload
                ).model_dump(mode="json")
        except (ValueError, KeyError) as error:
            raise ValidationError({"payload": str(error)}) from error
        if legacy and self.kind != self.payload["kind"]:
            raise ValidationError(
                {"payload": "Payload kind must match the artifact kind."}
            )
        if (legacy and (self.kind == self.Kind.FILE) != bool(self.file_id)) or (
            self.kind == self.Kind.FILE and not self.file_id
        ):
            raise ValidationError(
                {
                    "file": "File artifacts require a File reference; legacy non-file artifacts cannot have one."
                }
            )
        if self.created_by_message_id:
            self.check_conversation(
                "created_by_message",
                self.created_by_message.conversation_id,
                self.conversation_id,
            )
        if self.created_by_tool_call_id:
            self.check_conversation(
                "created_by_tool_call",
                self.created_by_tool_call.run.conversation_id,
                self.conversation_id,
            )
        if self.previous_revision_id:
            if self.previous_revision_id == self.pk:
                raise ValidationError(
                    {"previous_revision": "An artifact cannot revise itself."}
                )
            self.check_conversation(
                "previous_revision",
                self.previous_revision.conversation_id,
                self.conversation_id,
            )
            if self.previous_revision.kind != self.kind:
                raise ValidationError(
                    {"previous_revision": "Revisions must retain their artifact kind."}
                )
        if legacy and self.kind == self.Kind.FORM_PATCH:
            for source_id in self.payload["source_artifact_ids"]:
                if (
                    not type(self)
                    .objects.filter(pk=source_id, conversation_id=self.conversation_id)
                    .exists()
                ):
                    raise ValidationError(
                        {
                            "payload": "Form sources must be existing artifacts in this conversation."
                        }
                    )

    @classmethod
    def from_tool_result(
        cls, tool: "AIToolCall", request: "HttpRequest", lease_token: "UUID"
    ) -> list["AIArtifact"]:
        """Persist adapted results under the run lock with deterministic replay identities."""
        import json
        from uuid import uuid5

        from bloomerp.agents.artifacts.registry import AI_ARTIFACT_REGISTRY
        from bloomerp.agents.definition import AIArtifactToolResult, MessageContent

        from .ai_message_artifact import AIMessageArtifact

        artifacts = []
        with tool.run.locked() as run:
            run.leased_attempt(lease_token)
            if request.user.pk != run.initiated_by_id:
                raise ValidationError("Artifact actor must match the run actor")
            tool.refresh_from_db()
            if tool.status != "completed":
                return []
            existing = list(cls.objects.filter(created_by_tool_call=tool))
            if existing:
                return existing
            result = AIArtifactToolResult(
                tool_name=tool.tool_identifier,
                arguments=tool.arguments,
                result=tool.result or {},
            )
            # Validate the complete batch before writing any artifact.
            candidates = list(AI_ARTIFACT_REGISTRY.adapt_tool_result(result, request))
            for definition, adapter_key, candidate in candidates:
                identity = json.dumps(
                    [
                        definition.key,
                        definition.schema_version,
                        adapter_key,
                        candidate.key,
                    ],
                    separators=(",", ":"),
                )
                artifact_id = uuid5(tool.pk, identity)
                artifact, _created = cls.objects.get_or_create(
                    pk=artifact_id,
                    defaults={
                        "conversation": run.conversation,
                        "created_by_tool_call": tool,
                        "kind": definition.key,
                        "schema_version": definition.schema_version,
                        "payload": candidate.payload,
                        "file_id": candidate.file_id,
                    },
                )
                if artifact.payload != candidate.payload:
                    raise ValidationError(
                        "Adapter changed a previously persisted artifact"
                    )
                if candidate.display:
                    message = run.conversation.append_message(
                        message_id=uuid5(artifact_id, "presentation"),
                        role="assistant",
                        run=run,
                        content=MessageContent(
                            root=[{"type": "artifact", "position": 0}]
                        ),
                    )
                    AIMessageArtifact.objects.get_or_create(
                        message=message, position=0, defaults={"artifact": artifact}
                    )
                artifacts.append(artifact)
        return artifacts

    @classmethod
    def resolve_selections(
        cls, tokens: list[str], user: "AbstractBaseUser"
    ) -> list[dict[str, Any]]:
        """Resolve bounded signed candidates and recheck source permissions before ingestion."""
        from django.http import HttpRequest

        from bloomerp.agents.artifacts.selection import resolve_selection

        if len(tokens) > 20 or any(len(token) > 32768 for token in tokens):
            raise ValidationError("Too many or oversized attachments")
        request = HttpRequest()
        request.user = user
        try:
            return [resolve_selection(token, request) for token in tokens]
        except (ValueError, KeyError) as error:
            raise ValidationError("Attachment unavailable; select it again") from error
