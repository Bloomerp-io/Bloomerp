"""Conversation ownership and metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from bloomerp.agents.definition import MessageContent, RunUsage
from bloomerp.agents.runtime import AgentRuntimeMessage

from .base import AgentModel

if TYPE_CHECKING:
    from bloomerp.agents.definition import BrowserContext, RunBudgets
    from bloomerp.agents.mcp import AgentApprovalRules
    from bloomerp.agents.runtime import AgentRuntimeConfig
    from bloomerp.models.agents.ai_message import AIMessage
    from bloomerp.models.agents.ai_run import AIRun
    from bloomerp.models.users.user import AbstractBloomerpUser


class AIConversation(AgentModel):
    """Own a private transcript and its durable executions and artifacts."""

    class Meta(AgentModel.Meta):
        db_table = "bloomerp_ai_conversation"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["owner", "-datetime_updated"], name="ai_conv_owner_updated"
            )
        ]

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ARCHIVED = "archived", "Archived"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_conversations",
    )
    selected_agent = models.ForeignKey(
        "bloomerp.AIAgent",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations",
    )
    approval_rules = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Tool Approval Rules"),
        help_text=_(
            "Conversation approval policy for new tool calls. Can be changed during a conversation; pending approvals still require a decision."
        ),
    )
    title = models.CharField(max_length=255, default="AI conversation")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )

    def clean(self) -> None:
        """Validate conversation approval rules before persisting metadata."""
        from bloomerp.agents.mcp import AgentApprovalRules

        super().clean()
        try:
            AgentApprovalRules.model_validate(self.approval_rules)
        except ValueError as error:
            raise ValidationError(
                {"approval_rules": _("Invalid tool approval rules.")}
            ) from error

    def __str__(self) -> str:
        """Return the user-visible conversation title."""
        return self.title

    @property
    def number_of_messages(self) -> int:
        """Count normalized message records without loading their contents."""
        return self.messages.count()

    def edit_metadata(
        self,
        *,
        title: str | None = None,
        archived: bool | None = None,
        approval_rules: AgentApprovalRules | None = None,
    ) -> None:
        """Update metadata and live tool approval rules without stopping executions."""
        with transaction.atomic():
            conversation = type(self).objects.select_for_update().get(pk=self.pk)
            if title is not None:
                title = title.strip()
                if not title or len(title) > 255:
                    raise ValidationError(
                        "Conversation title must contain 1 to 255 characters"
                    )
                conversation.title = title
            if archived is not None:
                conversation.status = (
                    self.Status.ARCHIVED if archived else self.Status.OPEN
                )
            if approval_rules is not None:
                conversation.approval_rules = approval_rules.model_dump(mode="json")
            conversation.save()
        self.refresh_from_db()

    def transcript_page(
        self, *, before_sequence: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Read bounded text, safe progress and the replay cursor under the conversation lock."""
        from bloomerp.agents.mcp import AgentApprovalRules

        from .ai_approval import AIApproval

        if not 1 <= limit <= 100 or (
            before_sequence is not None and before_sequence < 1
        ):
            raise ValidationError("Invalid transcript bounds")
        with transaction.atomic():
            conversation = type(self).objects.select_for_update().get(pk=self.pk)
            query = conversation.messages.filter(role__in=["user", "assistant"])
            if before_sequence is not None:
                query = query.filter(sequence__lt=before_sequence)
            rows = list(
                query.prefetch_related("artifact_links").order_by("-sequence")[
                    : limit + 1
                ]
            )
            has_more = len(rows) > limit
            rows = list(reversed(rows[:limit]))
            run = conversation.runs.order_by("-datetime_created", "-pk").first()
            run_ids = {row.run_id for row in rows if row.run_id}
            if run and before_sequence is None:
                run_ids.add(run.pk)
            approvals = (
                AIApproval.objects.filter(tool_call__run_id__in=run_ids)
                .select_related("tool_call")
                .order_by("datetime_created")
            )
            cursor = (
                (run.events.aggregate(last=Max("sequence"))["last"] or 0) if run else 0
            )
            return {
                "conversation": {
                    "id": str(conversation.pk),
                    "title": conversation.title,
                    "status": conversation.status,
                    "approval_rules": AgentApprovalRules.model_validate(
                        conversation.approval_rules
                    ).model_dump(mode="json"),
                    "selected_agent_id": str(conversation.selected_agent_id)
                    if conversation.selected_agent_id
                    else None,
                },
                "messages": [
                    {
                        "id": str(row.pk),
                        "sequence": row.sequence,
                        "role": row.role,
                        "status": row.status,
                        "content": row.content_blocks,
                        "artifacts": [
                            {"id": str(link.artifact_id), "position": link.position}
                            for link in row.artifact_links.all()
                        ],
                        "created_at": row.datetime_created.isoformat(),
                    }
                    for row in rows
                ],
                "approvals": [
                    {
                        "id": str(item.pk),
                        "status": item.status,
                        "tool_identifier": item.tool_call.tool_identifier,
                        "tool_title": item.tool_call.display_title(),
                        "arguments": item.tool_call.arguments,
                        "created_at": item.datetime_created.isoformat(),
                        "run_id": str(item.tool_call.run_id),
                    }
                    for item in approvals
                ],
                "before_sequence": rows[0].sequence if rows and has_more else None,
                "run": {
                    "id": str(run.pk),
                    "status": run.status,
                    "client_message_id": str(run.trigger_message_id),
                    "cursor": cursor,
                    "cancel_requested": run.cancel_requested_at is not None,
                    "progress": run.progress_snapshot(),
                }
                if run
                else None,
            }

    def messages_to_runtime_messages(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        through_sequence: int | None = None,
    ) -> tuple[AgentRuntimeMessage, ...]:
        """Build bounded completed text history; reject unsupported input explicitly.

        The initial turn takes the most recent entries through its trigger. Resume
        callers supply only new user input, never streamed assistant output already
        represented by the private checkpoint. Artifact/tool resolution can extend
        this conversion without changing runtime or storage contracts.
        """
        if after_sequence < 0 or not 1 <= limit <= 1000:
            raise ValidationError("Invalid transcript bounds")
        query = self.messages.filter(sequence__gt=after_sequence, status="completed")
        if through_sequence is not None:
            query = query.filter(sequence__lte=through_sequence)
        if after_sequence:
            query = query.filter(role="user")
        messages = list(query.order_by("-sequence")[:limit])
        result = []
        for message in reversed(messages):
            blocks = MessageContent.model_validate(message.content_blocks).root
            from django.http import HttpRequest

            from bloomerp.agents.artifacts.registry import AI_ARTIFACT_REGISTRY
            from bloomerp.agents.definition import TextBlock

            request = HttpRequest()
            request.user = self.owner
            resolved = []
            links = {
                link.position: link.artifact
                for link in message.artifact_links.select_related("artifact")
            }
            for block in blocks:
                if block.type == "text":
                    resolved.append(block)
                elif block.type == "artifact":
                    artifact = links.get(block.position)
                    if artifact is None:
                        raise ValidationError("Missing artifact link")
                    try:
                        definition = AI_ARTIFACT_REGISTRY.get_type(
                            artifact.kind, artifact.schema_version
                        )
                        payload = definition.model.model_validate(artifact.payload)
                        if definition.authorize is not None:
                            definition.authorize(payload, request)
                        description = definition.describe(payload)
                        text = f"Artifact {artifact.pk}: {description.title}. {description.summary}"
                    except (PermissionDenied, LookupError, ValueError):
                        text = "Artifact unavailable."
                    resolved.append(TextBlock(text=text))
                else:
                    raise ValidationError("Unsupported runtime context block")
            blocks = resolved
            result.append(
                AgentRuntimeMessage(
                    role=message.role,
                    content=tuple(blocks),
                    message_id=message.pk,
                    sequence=message.sequence,
                )
            )
        return tuple(result)

    def append_message(
        self,
        *,
        content: MessageContent,
        role: Literal["user", "assistant", "system"],
        message_id: UUID,
        run: AIRun | None = None,
        status: str = "completed",
    ) -> AIMessage:
        """Allocate transcript sequence under the conversation lock and deduplicate IDs."""
        from .ai_message import AIMessage

        payload = MessageContent.model_validate(content).model_dump(mode="json")
        with transaction.atomic():
            conversation = type(self).objects.select_for_update().get(pk=self.pk)
            existing = AIMessage.objects.filter(pk=message_id).first()
            if existing is not None:
                if (
                    existing.conversation_id != self.pk
                    or existing.role != role
                    or existing.content_blocks != payload
                    or existing.run_id != (run.pk if run else None)
                ):
                    raise ValidationError(
                        "Message identity conflicts with existing content"
                    )
                return existing
            sequence = (self.messages.aggregate(last=Max("sequence"))["last"] or 0) + 1
            conversation.save(update_fields=["datetime_updated"])
            return AIMessage.objects.create(
                id=message_id,
                conversation=self,
                sequence=sequence,
                role=role,
                content_blocks=payload,
                run=run,
                status=status,
            )

    def create_run(
        self,
        *,
        trigger_message: AIMessage,
        initiated_by: AbstractBloomerpUser,
        config: AgentRuntimeConfig,
        budgets: RunBudgets,
        browser_context: BrowserContext | None = None,
    ) -> AIRun:
        """Create a pinned logical run while retaining the one-unfinished-run invariant."""
        from .ai_run import AIRun

        with transaction.atomic():
            conversation = type(self).objects.select_for_update().get(pk=self.pk)
            if conversation.status != self.Status.OPEN:
                raise ValidationError("Conversation is archived")
            if self.runs.filter(status__in=["queued", "running", "waiting"]).exists():
                raise ValidationError("A run is already active in this conversation")
            return AIRun.objects.create(
                conversation=self,
                trigger_message=trigger_message,
                initiated_by=initiated_by,
                agent_key=config.agent_key,
                agent_version=config.agent_version,
                config_snapshot=config.to_snapshot(),
                budgets=budgets,
                usage=RunUsage(),
                origin_browser_context=browser_context,
            )
