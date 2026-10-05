"""Instance-configured orchestration for durable agent conversations and MCP actions."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from bloomerp.agents.definition import (
    AgentError,
    BrowserContext,
    MessageContent,
    RunBudgets,
    RunEventPayload,
    RunUsage,
)
from bloomerp.agents.mcp import (
    AgentApprovalRules,
    AgentMcpClient,
    LocalMcpClient,
    McpToolCoordinator,
)
from bloomerp.agents.runtime import (
    AgentRuntime,
    AgentRuntimeCheckpoint,
    AgentRuntimeConfig,
    AgentRuntimeContext,
    AgentRuntimeCredentials,
    AgentRuntimeResumeRequest,
    AgentRuntimeRunFailedEvent,
    AgentRuntimeRunRequest,
    AgentRuntimeToolCoordinator,
)
from bloomerp.config.definition import BloomerpAgentSettings, get_bloomerp_config
from bloomerp.services.mcp.client import MCPUnavailableError

if TYPE_CHECKING:
    from bloomerp.models.agents import (
        AIAgent,
        AIConversation,
        AIRun,
        AIRunAttempt,
        AIRunEvent,
    )
    from bloomerp.models.users.user import AbstractBloomerpUser


logger = logging.getLogger(__name__)
_live_tasks: set[asyncio.Task[None]] = set()


class AgentControllerNotImplemented(NotImplementedError):
    """Indicate a capability that has not yet been enabled in this executor."""


class AgentControllerPayload(BaseModel):
    """Validate transport data separately from ORM records and runtime DTOs."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgentChatRequest(AgentControllerPayload):
    """Submit structured user content without accepting a client-supplied actor.

    client_message_id is optional for the existing draft client; callers should
    supply a stable UUID for retry deduplication. The controller generates one
    when absent. queue/steer reserves the future active-run input policy; this
    text-only executor currently rejects input while a run is unfinished.
    Browser context is an origin hint, never authorization to act on a target.
    """

    content: MessageContent
    attachments: list[str] = Field(default_factory=list, max_length=20)
    conversation_id: UUID | None = None
    agent_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("agent_id", "model_id")
    )
    approval_rules: AgentApprovalRules | None = None
    client_message_id: UUID | None = None
    active_run_behavior: Literal["queue", "steer"] = "queue"
    browser_context: BrowserContext | None = None


class AgentSubmission(AgentControllerPayload):
    """Acknowledge a durably accepted submission without waiting for model output."""

    conversation_id: UUID
    run_id: UUID
    message_id: UUID | None = None
    disposition: Literal["started", "queued", "steered", "resumed"]
    artifact_ids: list[UUID] = Field(default_factory=list)


class AgentRunCommand(AgentControllerPayload):
    """Address a run whose ownership must be checked by the bound controller."""

    run_id: UUID


class AgentApprovalDecision(AgentControllerPayload):
    """Request a decision; eligibility and proposal validity remain server checks."""

    approval_id: UUID
    decision: Literal["approved", "rejected"]
    reason: str = ""


class AgentReplayRequest(AgentControllerPayload):
    """Request a bounded page using a sequence cursor scoped to one logical run."""

    conversation_id: UUID
    run_id: UUID
    after_sequence: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=100, ge=1, le=500, strict=True)


class AgentHistoryRequest(AgentControllerPayload):
    """Page through only the bound user's conversations."""

    request_id: UUID
    search: str = Field(default="", max_length=255)
    archived: bool = False
    cursor: str | None = Field(default=None, max_length=2048)
    limit: int = Field(default=30, ge=1, le=100)


class AgentConversationRequest(AgentControllerPayload):
    """Load an owned transcript with a stable message sequence cursor."""

    request_id: UUID
    conversation_id: UUID
    before_sequence: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=100)


class AgentConversationEdit(AgentControllerPayload):
    """Change conversation metadata without permitting ownership changes."""

    request_id: UUID
    conversation_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=255)
    archived: bool | None = None
    agent_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("agent_id", "model_id")
    )
    approval_rules: AgentApprovalRules | None = None


class AgentPublishedEvent(AgentControllerPayload):
    """Expose a committed event without sending raw provider checkpoint history."""

    conversation_id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    event_type: str
    payload: RunEventPayload


class AgentReplayPage(AgentControllerPayload):
    """Return committed public events and a continuation cursor for the same run."""

    events: tuple[AgentPublishedEvent, ...]
    next_sequence: int = Field(ge=0)
    has_more: bool


class AgentController:
    """Coordinate private, persisted text runs independently of socket lifetime.

    Persistence invariants live on models. The controller authorizes the actor,
    resolves instance settings, dispatches attempts, and publishes committed events.
    MCP endpoints retain authorization; persisted approvals gate their execution.
    """

    def __init__(
        self,
        user: AbstractBloomerpUser,
        *,
        tab_id: UUID | None = None,
        origin: str | None = None,
    ) -> None:
        """Bind server identity without reading secrets, writing rows, or opening clients."""
        self.user = user
        self.tab_id = tab_id
        self.origin = origin

    def instance_settings(self) -> BloomerpAgentSettings:
        """Resolve agent settings from the project's Bloomerp configuration."""
        options = get_bloomerp_config().bloomai_settings
        if options is None:
            raise ImproperlyConfigured(
                "BLOOMERP_CONFIG.bloomai_settings is not configured"
            )
        return options

    def available_agents(self) -> list[dict[str, str]]:
        """List enabled agents granted to the actor using safe picker metadata."""
        from bloomerp.agents.access import AIAgentAccessManager

        self.authorize()
        query = AIAgentAccessManager(self.user).get_accessible_queryset()
        return [
            {"id": str(agent.pk), "name": agent.name}
            for agent in query.filter(enabled=True)
            .exclude(credentials_encrypted={})
            .order_by("name")
        ]

    def select_agent(self, agent_id: UUID | None) -> AIAgent:
        """Require an explicit use grant or creator access for each new run."""
        from bloomerp.agents.access import AIAgentAccessManager

        query = (
            AIAgentAccessManager(self.user)
            .get_accessible_queryset()
            .filter(enabled=True)
            .exclude(credentials_encrypted={})
        )
        agent = (
            query.filter(pk=agent_id).first()
            if agent_id
            else query.order_by("name").first()
        )
        if agent is None:
            raise PermissionDenied(
                "The selected AI agent is unavailable or you no longer have access. Configure an AI agent or contact your administrator."
            )
        return agent

    def get_config(self, agent_id: UUID | None = None) -> AgentRuntimeConfig:
        """Build a new run's configuration from a permitted model record."""
        return self.select_agent(agent_id).runtime_config()

    def get_credentials(self, config: AgentRuntimeConfig) -> AgentRuntimeCredentials:
        """Resolve current credentials from the pinned model identity for each attempt."""
        from bloomerp.models.agents import AIAgent

        if not config.model_record_id:
            raise ImproperlyConfigured("This run has no configured AI agent")
        from bloomerp.agents.access import AIAgentAccessManager

        model = AIAgent.objects.get(pk=config.model_record_id)
        if not AIAgentAccessManager(self.user).can_use(model):
            raise PermissionDenied("You no longer have access to this AI agent.")
        return model.runtime_credentials(config.provider)

    def get_runtime(self, config: AgentRuntimeConfig) -> AgentRuntime:
        """Pass the pinned configuration to the registered provider's fresh runtime factory."""
        from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY

        provider = AI_PROVIDER_REGISTRY.get(config.provider)
        if provider is None:
            raise ImproperlyConfigured("Unknown AI provider")
        runtime = provider.runtime_factory(config)
        if not isinstance(runtime, AgentRuntime):
            raise ImproperlyConfigured("Runtime factory must implement AgentRuntime")
        return runtime

    def get_tool_coordinator(
        self, run: AIRun, attempt: AIRunAttempt
    ) -> AgentRuntimeToolCoordinator:
        """Bind shared MCP execution and live progress to the persisted actor and executor lease."""
        return McpToolCoordinator(
            run, attempt, self.get_mcp_client(run), publish=async_to_sync(self.publish)
        )

    def get_mcp_client(self, run: AIRun) -> LocalMcpClient:
        """Use the socket-bound instance origin, with an explicit fallback for non-browser runs."""
        origin = (run.origin_browser_context or {}).get(
            "instance_origin"
        ) or self.instance_settings().mcp_origin
        return AgentMcpClient(
            run.initiated_by_id,
            origin,
            agent_id=run.config_snapshot.get("model_record_id"),
        )

    def authorize(self) -> None:
        """Require a current active authenticated account, including on worker execution."""
        if (
            not self.user.is_authenticated
            or not get_user_model()
            .objects.filter(pk=self.user.pk, is_active=True)
            .exists()
        ):
            raise PermissionDenied("Agent access denied")

    def load_run(self, run_id: UUID) -> AIRun:
        """Scope run access to its conversation owner, even for administrators."""
        from bloomerp.models.agents import AIRun

        self.authorize()
        run = (
            AIRun.objects.filter(pk=run_id, conversation__owner_id=self.user.pk)
            .select_related("conversation", "trigger_message")
            .first()
        )
        if run is None:
            raise PermissionDenied("Agent access denied")
        return run

    def load_conversation(self, conversation_id: UUID) -> AIConversation:
        """Enforce conversation ownership independently of runtime/provider configuration."""
        from bloomerp.models.agents import AIConversation

        self.authorize()
        conversation = AIConversation.objects.filter(
            pk=conversation_id, owner_id=self.user.pk
        ).first()
        if conversation is None:
            raise PermissionDenied("Conversation access denied")
        return conversation

    def conversation_history(self, request: AgentHistoryRequest) -> dict[str, Any]:
        """Return a private keyset-paginated list with current run status and no message contents."""
        from django.core import signing
        from django.db.models import OuterRef, Q, Subquery
        from django.utils.dateparse import parse_datetime

        from bloomerp.models.agents import AIConversation, AIRun

        self.authorize()
        query = AIConversation.objects.filter(
            owner_id=self.user.pk, status="archived" if request.archived else "open"
        )
        if request.search.strip():
            query = query.filter(title__icontains=request.search.strip())
        if request.cursor:
            try:
                value = signing.loads(request.cursor, salt="agent.history")
                date = parse_datetime(value["date"])
                pk = UUID(value["id"])
                if date is None:
                    raise ValueError
            except (signing.BadSignature, KeyError, ValueError, TypeError):
                raise DjangoValidationError("Invalid history cursor") from None
            query = query.filter(
                Q(datetime_updated__lt=date) | Q(datetime_updated=date, pk__lt=pk)
            )
        runs = AIRun.objects.filter(conversation_id=OuterRef("pk")).order_by(
            "-datetime_created", "-pk"
        )
        rows = list(
            query.annotate(run_status=Subquery(runs.values("status")[:1])).order_by(
                "-datetime_updated", "-pk"
            )[: request.limit + 1]
        )
        selected = rows[: request.limit]
        last = selected[-1] if selected else None
        return {
            "conversations": [
                {
                    "id": str(row.pk),
                    "title": row.title,
                    "status": row.status,
                    "updated_at": row.datetime_updated.isoformat(),
                    "run_status": row.run_status,
                }
                for row in selected
            ],
            "cursor": signing.dumps(
                {"date": last.datetime_updated.isoformat(), "id": str(last.pk)},
                salt="agent.history",
            )
            if last and len(rows) > request.limit
            else None,
        }

    def conversation_detail(self, request: AgentConversationRequest) -> dict[str, Any]:
        """Read a consistent transcript and continuation cursor after authorizing its owner."""
        return self.load_conversation(request.conversation_id).transcript_page(
            before_sequence=request.before_sequence, limit=request.limit
        )

    def edit_conversation(self, request: AgentConversationEdit) -> dict[str, Any]:
        """Authorize owner-only edits to model selection, metadata and live approval rules."""
        conversation = self.load_conversation(request.conversation_id)
        if request.agent_id is not None:
            selected = self.select_agent(request.agent_id)
            conversation.selected_agent = selected
            conversation.save(update_fields=["selected_agent"])
        conversation.edit_metadata(
            title=request.title,
            archived=request.archived,
            approval_rules=request.approval_rules,
        )
        return {
            "conversation": {
                "id": str(conversation.pk),
                "title": conversation.title,
                "status": conversation.status,
                "approval_rules": AgentApprovalRules.model_validate(
                    conversation.approval_rules
                ).model_dump(mode="json"),
            }
        }

    def accept_message(self, request: AgentChatRequest) -> AgentSubmission:
        """Authorize and atomically create one message/run, deduplicating client retries."""
        from bloomerp.models.agents import AIArtifact, AIConversation, AIMessage

        self.authorize()
        if not request.content.root or any(
            block.type != "text" or block.format != "plain"
            for block in request.content.root
        ):
            raise DjangoValidationError(
                "Only plain text input is supported at this boundary"
            )
        if (
            not any(block.text.strip() for block in request.content.root)
            and not request.attachments
        ):
            raise DjangoValidationError("Message must not be blank")
        selections = AIArtifact.resolve_selections(request.attachments, self.user)
        message_id = request.client_message_id or uuid4()
        with transaction.atomic():
            # Serialize initial-conversation retries for this actor as well as existing conversations.
            get_user_model().objects.select_for_update().get(pk=self.user.pk)
            old = (
                AIMessage.objects.filter(pk=message_id)
                .select_related("conversation")
                .first()
            )
            if old is not None:
                if old.conversation.owner_id != self.user.pk or (
                    request.conversation_id
                    and old.conversation_id != request.conversation_id
                ):
                    raise PermissionDenied("Agent access denied")
                if (
                    old.role != "user"
                    or [
                        block
                        for block in old.content_blocks
                        if block["type"] != "artifact"
                    ]
                    != request.content.model_dump(mode="json")
                    or old.attachment_specs() != selections
                ):
                    raise DjangoValidationError(
                        "Message identity conflicts with existing content"
                    )
                run = old.triggered_runs.first()
                if run is None:
                    raise DjangoValidationError("Message has no execution")
                return AgentSubmission(
                    conversation_id=old.conversation_id,
                    run_id=run.pk,
                    message_id=old.pk,
                    artifact_ids=list(
                        old.artifact_links.order_by("position").values_list(
                            "artifact_id", flat=True
                        )
                    ),
                    disposition="started",
                )
            if request.conversation_id:
                conversation = (
                    AIConversation.objects.select_for_update()
                    .filter(pk=request.conversation_id, owner_id=self.user.pk)
                    .first()
                )
                if conversation is None:
                    raise PermissionDenied("Agent access denied")
            else:
                conversation = AIConversation.objects.create(
                    owner=self.user,
                    created_by=self.user,
                    updated_by=self.user,
                    title=next(
                        (
                            block.text.strip()
                            for block in request.content.root
                            if block.text.strip()
                        ),
                        "Attachments",
                    )[:255],
                )
            if conversation.runs.filter(
                status__in=["queued", "running", "waiting"]
            ).exists():
                raise DjangoValidationError(
                    "A response is already active; wait or stop it before sending another message"
                )
            selected = self.select_agent(
                request.agent_id or conversation.selected_agent_id
            )
            if request.approval_rules is not None:
                conversation.approval_rules = request.approval_rules.model_dump(
                    mode="json"
                )
            config = selected.runtime_config().model_copy(
                update={"approval_rules": conversation.approval_rules}
            )
            conversation.selected_agent = selected
            conversation.save(update_fields=["selected_agent", "approval_rules"])
            message = conversation.append_message(
                content=request.content, role="user", message_id=message_id
            )
            message.attach_artifacts(selections)
            context = (
                request.browser_context.model_copy(
                    update={"tab_id": self.tab_id, "instance_origin": self.origin}
                )
                if request.browser_context
                else BrowserContext(tab_id=self.tab_id, instance_origin=self.origin)
            )
            run = conversation.create_run(
                trigger_message=message,
                initiated_by=self.user,
                config=config,
                budgets=selected.run_budgets(),
                browser_context=context,
            )
            return AgentSubmission(
                conversation_id=conversation.pk,
                run_id=run.pk,
                message_id=message.pk,
                artifact_ids=list(
                    message.artifact_links.order_by("position").values_list(
                        "artifact_id", flat=True
                    )
                ),
                disposition="started",
            )

    async def execute(self, request: AgentChatRequest) -> AgentSubmission:
        """Durably accept input and dispatch without tying execution to socket lifetime."""
        self.instance_settings()
        submission = await database_sync_to_async(self.accept_message)(request)
        run = await database_sync_to_async(self.load_run)(submission.run_id)
        if run.status == "queued":
            self.schedule_dispatch(run.pk)
        return submission

    def worker_mode(self) -> bool:
        """Use configured external Celery brokers; memory-only development runs inline."""
        from bloomerp.celery.utils import is_celery_available

        return is_celery_available() and not str(
            getattr(settings, "CELERY_BROKER_URL", "")
        ).startswith("memory://")

    def schedule_dispatch(self, run_id: UUID) -> None:
        """Keep even slow broker dispatch outside the socket's receive handler."""
        task = asyncio.create_task(self.dispatch(run_id))
        _live_tasks.add(task)
        task.add_done_callback(self.task_finished)

    async def dispatch(self, run_id: UUID) -> None:
        """Dispatch only IDs to workers, or retain a managed task on the application loop."""
        try:
            if self.worker_mode():
                from bloomerp.celery.tasks.agent_task import execute_agent_run

                await database_sync_to_async(execute_agent_run.delay)(
                    str(run_id), str(self.user.pk)
                )
            else:
                task = asyncio.create_task(
                    self.run_attempt(
                        run_id, execution_mode="inline", executor_id=f"inline:{uuid4()}"
                    )
                )
                _live_tasks.add(task)
                task.add_done_callback(self.task_finished)
        except Exception:  # noqa: BLE001 - never expose broker credentials in errors
            run = await database_sync_to_async(self.load_run)(run_id)
            event = await database_sync_to_async(run.fail_queued)(
                AgentError(
                    code="dispatch_failed",
                    message="The agent could not be scheduled.",
                    retryable=True,
                )
            )
            if event:
                await self.publish(event)

    @staticmethod
    def task_finished(task: asyncio.Task[None]) -> None:
        """Release managed task references and consume unexpected background failures."""
        _live_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent executor stopped unexpectedly; inspect durable run state"
            )

    async def run_attempt(
        self,
        run_id: UUID,
        *,
        execution_mode: Literal["inline", "worker"],
        executor_id: str,
    ) -> None:
        """Lease, execute or resume, and commit each event before requesting the next."""
        run = await database_sync_to_async(self.load_run)(run_id)
        try:
            options = self.instance_settings()
        except (ImproperlyConfigured, ValueError):
            event = await database_sync_to_async(run.fail_queued)(
                AgentError(
                    code="configuration_unavailable",
                    message="Agent execution settings are unavailable.",
                    retryable=True,
                )
            )
            if event:
                await self.publish(event)
            return
        lease = timedelta(seconds=options.lease_seconds)
        try:
            attempt = await database_sync_to_async(run.create_attempt)(
                execution_mode=execution_mode,
                executor_id=executor_id,
                lease_duration=lease,
            )
        except DjangoValidationError:
            return  # Duplicate delivery, a live lease, or an already terminal run.
        run = await database_sync_to_async(self.load_run)(run_id)
        runtime: AgentRuntime | None = None
        monitor: asyncio.Task[None] | None = None
        iterator = None
        last_event_kind: str | None = None
        try:
            config = run.runtime_config()
            runtime = self.get_runtime(config)
            context = AgentRuntimeContext(
                user_id=str(run.initiated_by_id),
                conversation_id=run.conversation_id,
                origin_browser_context=run.origin_browser_context,
            )
            messages = await database_sync_to_async(
                run.conversation.messages_to_runtime_messages
            )(
                after_sequence=run.consumed_message_sequence if run.checkpoint else 0,
                through_sequence=run.trigger_message.sequence
                if run.trigger_message_id
                else None,
                limit=options.history_limit,
            )
            coordinator = self.get_tool_coordinator(run, attempt)
            tools = await database_sync_to_async(self.get_mcp_client(run).definitions)()
            request = AgentRuntimeRunRequest(
                run_id=run.pk,
                attempt_id=attempt.pk,
                config=config,
                context=context,
                messages=messages,
                tools=tools,
                budgets=RunBudgets.model_validate(run.budgets),
                usage=RunUsage.model_validate(run.usage),
            )
            credentials = await database_sync_to_async(self.get_credentials)(config)
            if run.checkpoint:
                iterator = runtime.resume(
                    AgentRuntimeResumeRequest(
                        run=request,
                        checkpoint=AgentRuntimeCheckpoint.model_validate(
                            run.checkpoint
                        ),
                    ),
                    credentials=credentials,
                    coordinator=coordinator,
                )
            else:
                iterator = runtime.execute(
                    request, credentials=credentials, coordinator=coordinator
                )
            monitor = asyncio.create_task(self.monitor(run, attempt, runtime, lease))
            terminal = False
            async for event in iterator:
                last_event_kind = event.kind
                stored = await database_sync_to_async(run.apply_runtime_event)(
                    event, lease_token=attempt.lease_token
                )
                await self.publish(stored)
                if stored.event_type in {
                    "run.completed",
                    "run.cancelled",
                    "run.failed",
                    "run.paused",
                }:
                    terminal = True
                    break
            if not terminal:
                raise RuntimeError("Runtime ended without a terminal event")
        except asyncio.CancelledError:
            # Process shutdown leaves a fenced, recoverable attempt rather than cancelling the user's run.
            raise
        except Exception as error:  # noqa: BLE001 - sanitize provider/configuration failures before persistence
            logger.warning(
                "Agent execution failed: %s after %s",
                type(error).__name__,
                last_event_kind,
            )
            await database_sync_to_async(attempt.refresh_from_db)()
            failure = AgentRuntimeRunFailedEvent(
                run_id=run.pk,
                attempt_id=attempt.pk,
                usage=RunUsage.model_validate(attempt.usage),
                error=AgentError(
                    code="execution_failed",
                    message=str(error)
                    if isinstance(error, MCPUnavailableError)
                    else "The agent could not complete this response.",
                    retryable=True,
                    details={
                        "exception_type": type(error).__name__,
                        "last_event_kind": last_event_kind,
                    },
                ),
            )
            try:
                stored = await database_sync_to_async(run.apply_runtime_event)(
                    failure, lease_token=attempt.lease_token
                )
            except DjangoValidationError:
                return  # A replaced/expired executor must not write or publish.
            await self.publish(stored)
        finally:
            if monitor:
                monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor
            if iterator is not None and hasattr(iterator, "aclose"):
                await iterator.aclose()
            if runtime is not None:
                await runtime.aclose()
        run = await database_sync_to_async(self.load_run)(run_id)
        if run.status == "queued":
            self.schedule_dispatch(run_id)

    async def monitor(
        self, run: AIRun, attempt: AIRunAttempt, runtime: AgentRuntime, lease: timedelta
    ) -> None:
        """Renew leases and observe cancellation even while a provider produces no tokens."""
        while True:
            await asyncio.sleep(min(2, lease.total_seconds() / 3))
            try:
                cancel = await database_sync_to_async(run.heartbeat)(
                    attempt.lease_token, lease_duration=lease
                )
            except Exception:  # noqa: BLE001 - stop local work when its durable lease cannot be renewed
                await runtime.cancel(run.pk, attempt_id=attempt.pk)
                return
            if cancel:
                await runtime.cancel(run.pk, attempt_id=attempt.pk)
                return

    async def cancel(self, run_id: UUID) -> None:
        """Persist owner-authorized cancellation; executors observe it across processes."""
        run = await database_sync_to_async(self.load_run)(run_id)
        event = await database_sync_to_async(run.request_cancel)()
        if event:
            await self.publish(event)

    async def resume(self, run_id: UUID) -> AgentSubmission:
        """Recover queued or expired text attempts without bypassing approval waits."""
        run = await database_sync_to_async(self.load_run)(run_id)
        if run.status not in {"queued", "running"}:
            raise DjangoValidationError(
                "Only queued or interrupted executions can be resumed here"
            )
        if await database_sync_to_async(
            run.attempts.filter(
                status="running", lease_expires_at__gt=timezone.now()
            ).exists
        )():
            raise DjangoValidationError("Run already has a live executor")
        self.schedule_dispatch(run.pk)
        return AgentSubmission(
            conversation_id=run.conversation_id,
            run_id=run.pk,
            message_id=run.trigger_message_id,
            disposition="resumed",
        )

    async def decide_approval(self, request: AgentApprovalDecision) -> None:
        """Commit an owner-authorized decision and resume only when all decisions are resolved."""
        event, run_id = await database_sync_to_async(self.record_approval)(request)
        if event:
            await self.publish(event)
        run = await database_sync_to_async(self.load_run)(run_id)
        if run.status == "queued":
            self.schedule_dispatch(run_id)

    def record_approval(
        self, request: AgentApprovalDecision
    ) -> tuple[AIRunEvent | None, UUID]:
        """Resolve approval ownership before invoking the model's atomic decision method."""
        from bloomerp.models.agents import AIApproval

        self.authorize()
        approval = (
            AIApproval.objects.filter(
                pk=request.approval_id,
                tool_call__run__conversation__owner_id=self.user.pk,
            )
            .select_related("tool_call__run__conversation")
            .first()
        )
        if approval is None:
            raise PermissionDenied("Approval access denied")
        return approval.decide(
            self.user, request.decision, request.reason
        ), approval.tool_call.run_id

    async def publish(self, event: AIRunEvent) -> None:
        """Deliver only safe committed events; replay remains authoritative if delivery fails."""
        if event.event_type == "checkpoint.created":
            return
        layer = get_channel_layer()
        if layer is None:
            return
        from bloomerp.channels.agents.events import agent_user_group_name

        try:
            payload = await database_sync_to_async(event.public_payload)()
            await layer.group_send(
                agent_user_group_name(self.user.pk),
                {"type": "agent.event", "payload": payload},
            )
        except Exception:  # noqa: BLE001 - a transport outage must not roll back or fail committed execution
            logger.warning(
                "Agent event delivery failed; committed events remain available for replay"
            )

    def replay_page(self, request: AgentReplayRequest) -> AgentReplayPage:
        """Reconcile pending cancellation and replay bounded owner-scoped public events."""
        run = self.load_run(request.run_id)
        if run.conversation_id != request.conversation_id:
            raise PermissionDenied("Agent access denied")
        if run.cancel_requested_at and run.status not in {
            "completed",
            "cancelled",
            "failed",
        }:
            # A lost executor cannot acknowledge Stop. Once its lease expires,
            # use the same locked cancellation path to release the conversation.
            run.request_cancel()
        rows = list(
            run.events.filter(sequence__gt=request.after_sequence).exclude(
                event_type="checkpoint.created"
            )[: request.limit + 1]
        )
        selected = rows[: request.limit]
        return AgentReplayPage(
            events=tuple(
                AgentPublishedEvent(
                    conversation_id=run.conversation_id,
                    run_id=run.pk,
                    sequence=row.sequence,
                    event_type=row.event_type,
                    payload=row.payload,
                )
                for row in selected
            ),
            next_sequence=selected[-1].sequence if selected else request.after_sequence,
            has_more=len(rows) > request.limit,
        )

    async def replay(self, request: AgentReplayRequest) -> AgentReplayPage:
        """Return owner-authorized committed events for reconnect or missed delivery."""
        return await database_sync_to_async(self.replay_page)(request)
