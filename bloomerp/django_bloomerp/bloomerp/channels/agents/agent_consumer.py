"""Authenticated browser bridge for tab discovery, navigation, and future chat."""

from time import monotonic
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import Field, JsonValue, ValidationError

from bloomerp.agents.controller import (
    AgentApprovalDecision,
    AgentChatRequest,
    AgentController,
    AgentControllerNotImplemented,
    AgentControllerPayload,
    AgentConversationEdit,
    AgentConversationRequest,
    AgentHistoryRequest,
    AgentReplayRequest,
    AgentRunCommand,
)
from bloomerp.agents.definition import BrowserContext
from bloomerp.channels.agents.events import agent_tab_group_name, agent_user_group_name
from bloomerp.router import router


class AgentChatEnvelope(AgentControllerPayload):
    """Validate the draft chat wire format without accepting an actor or tab override."""

    type: Literal["chat.message"]
    message: str
    attachments: list[str] = Field(default_factory=list, max_length=20)
    conversation_id: UUID | None = None
    client_message_id: UUID | None = None
    active_run_behavior: Literal["queue", "steer"] = "queue"
    page: dict[str, JsonValue] | None = None


@router.register(
    path="ws/agents/<uuid:tab_id>/",
    name="Agent browser connection",
    route_type="websocket",
)
class AgentConsumer(AsyncJsonWebsocketConsumer):
    """Connect an authenticated user's tab to browser commands and future chat."""

    controller: AgentController
    group_name: str | None = None
    user_group_name: str | None = None
    tab_id: str | None = None
    page_state: dict[str, Any] | None = None

    async def connect(self) -> None:
        """Authenticate the session and subscribe only to this user's tab group."""
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        # Session-authenticated sockets must originate from this same instance.
        headers = dict(self.scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin1")
        host = headers.get(b"host", b"").decode("latin1")
        if not origin or urlsplit(origin).netloc != host:
            await self.close(code=4403)
            return
        self.tab_id = str(self.scope["url_route"]["kwargs"]["tab_id"])
        self.controller = AgentController(user, tab_id=UUID(self.tab_id), origin=origin)
        self.group_name = agent_tab_group_name(user.pk, self.tab_id)
        self.user_group_name = agent_user_group_name(user.pk)
        self.pending_commands: dict[str, tuple[str, float]] = {}
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection.ready", "tab_id": self.tab_id})

    async def disconnect(self, close_code: int) -> None:
        """Release tab and discovery subscriptions when the browser disconnects."""
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if self.user_group_name:
            await self.channel_layer.group_discard(
                self.user_group_name, self.channel_name
            )

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Route browser presence, command results, and chat through separate hooks."""
        if not isinstance(content, dict):
            await self.send_json(
                {"type": "protocol.error", "message": "Expected an object"}
            )
            return
        message_type = content.get("type")
        if message_type == "tab.state" and isinstance(content.get("page"), dict):
            await self.update_tab_state(content["page"])
        elif message_type == "command.result":
            await self.handle_command_result(content)
        elif message_type == "chat.message":
            await self.handle_chat_message(content)
        elif message_type in {
            "chat.history",
            "chat.conversation",
            "chat.edit_conversation",
            "chat.resume",
            "chat.cancel",
            "chat.approval",
            "chat.replay",
        }:
            await self.handle_agent_action(content)
        else:
            await self.send_json(
                {"type": "protocol.error", "message": "Unknown message"}
            )

    async def update_tab_state(self, page: dict[str, Any]) -> None:
        """Keep validated browser metadata available to live discovery probes."""
        if not all(
            isinstance(page.get(key), str) for key in ("page_id", "url", "title")
        ):
            await self.send_json(
                {"type": "protocol.error", "message": "Invalid page state"}
            )
            return
        self.page_state = {
            "page_id": page["page_id"],
            "url": page["url"],
            "title": page["title"],
            "visible": page.get("visible") is True,
            "focused": page.get("focused") is True,
        }
        await self.send_json({"type": "tab.registered", "page_id": page["page_id"]})

    async def handle_command_result(self, result: dict[str, Any]) -> None:
        """Reply only to a pending server command issued to this exact connection."""
        command_id = result.get("command_id")
        if not isinstance(command_id, str) or command_id not in self.pending_commands:
            return
        status = result.get("status")
        if not isinstance(status, str) or status not in {
            "accepted",
            "completed",
            "failed",
        }:
            return
        if not isinstance(result.get("result"), dict):
            return
        reply_channel, expiry = self.pending_commands.pop(command_id)
        if expiry > monotonic():
            await self.channel_layer.send(
                reply_channel,
                {
                    "type": "agent.result",
                    "status": status,
                    "result": result["result"],
                },
            )

    async def agent_discover(self, event: dict[str, Any]) -> None:
        """Reply to a user-scoped discovery probe after the browser has registered."""
        if self.page_state is not None:
            await self.channel_layer.send(
                event["reply_channel"],
                {
                    "type": "agent.tab",
                    "tab_id": self.tab_id,
                    "channel_name": self.channel_name,
                    "page": self.page_state,
                },
            )

    async def agent_command(self, event: dict[str, Any]) -> None:
        """Remember a server-owned reply address before delivering a browser command."""
        now = monotonic()
        self.pending_commands = {
            key: value for key, value in self.pending_commands.items() if value[1] > now
        }
        command = event["payload"]
        self.pending_commands[command["command_id"]] = (
            event["reply_channel"],
            now + 10,
        )
        await self.send_json(command)

    async def handle_chat_message(self, message: dict[str, Any]) -> None:
        """Forward validated chat input through the controller's submission boundary."""
        await self.handle_agent_action(message)

    async def handle_agent_action(self, message: dict[str, Any]) -> None:
        """Route transport commands without implementing persistence or model execution."""
        action = message.get("type")
        payload = {key: value for key, value in message.items() if key != "type"}
        try:
            if action == "chat.history":
                data = await database_sync_to_async(
                    self.controller.conversation_history
                )(AgentHistoryRequest.model_validate(payload))
                response = {"status": "history", **data}
            elif action == "chat.conversation":
                data = await database_sync_to_async(
                    self.controller.conversation_detail
                )(AgentConversationRequest.model_validate(payload))
                response = {"status": "conversation", **data}
            elif action == "chat.edit_conversation":
                data = await database_sync_to_async(self.controller.edit_conversation)(
                    AgentConversationEdit.model_validate(payload)
                )
                response = {"status": "updated", **data}
            elif action == "chat.message":
                envelope = AgentChatEnvelope.model_validate(message)
                if not envelope.message.strip() and not envelope.attachments:
                    await self.send_json(
                        {
                            "type": "protocol.error",
                            "message": "Message must not be blank",
                        }
                    )
                    return
                origin = BrowserContext(
                    tab_id=UUID(self.tab_id),
                    page_id=(self.page_state or {}).get("page_id"),
                )
                submission = await self.controller.execute(
                    AgentChatRequest(
                        content=[{"type": "text", "text": envelope.message}],
                        conversation_id=envelope.conversation_id,
                        client_message_id=envelope.client_message_id,
                        active_run_behavior=envelope.active_run_behavior,
                        browser_context=origin,
                        attachments=envelope.attachments,
                    )
                )
                response = {
                    "status": "accepted",
                    "client_message_id": str(submission.message_id),
                    **submission.model_dump(mode="json"),
                }
            elif action == "chat.resume":
                command = AgentRunCommand.model_validate(payload)
                submission = await self.controller.resume(command.run_id)
                response = {
                    "status": "accepted",
                    "client_message_id": str(submission.message_id),
                    **submission.model_dump(mode="json"),
                }
            elif action == "chat.cancel":
                command = AgentRunCommand.model_validate(payload)
                await self.controller.cancel(command.run_id)
                response = {"status": "accepted"}
            elif action == "chat.approval":
                await self.controller.decide_approval(
                    AgentApprovalDecision.model_validate(payload)
                )
                response = {
                    "status": "accepted",
                    "approval_id": str(payload["approval_id"]),
                }
            elif action == "chat.replay":
                page = await self.controller.replay(
                    AgentReplayRequest.model_validate(payload)
                )
                response = {
                    "status": "replay",
                    "run_id": str(payload["run_id"]),
                    **page.model_dump(mode="json"),
                }
            else:
                await self.send_json(
                    {"type": "protocol.error", "message": "Unknown agent action"}
                )
                return
        except ValidationError:
            await self.send_json(
                {"type": "protocol.error", "message": "Invalid agent request"}
            )
            return
        except DjangoValidationError as error:
            response = {"status": "failed", "message": error.messages[0]}
        except ImproperlyConfigured:
            response = {
                "status": "unavailable",
                "message": "BloomAI is not configured for this instance",
            }
        except PermissionDenied:
            response = {
                "status": "forbidden",
                "message": "Agent operation is not permitted",
            }
        except AgentControllerNotImplemented:
            response = {
                "status": "unavailable",
                "message": "Agent controller execution is not implemented yet",
            }
        if "request_id" in message:
            response["request_id"] = message["request_id"]
        if "approval_id" in message:
            response["approval_id"] = message["approval_id"]
        if "run_id" in message and "run_id" not in response:
            response["run_id"] = message["run_id"]
        if "client_message_id" in message and "client_message_id" not in response:
            response["client_message_id"] = message["client_message_id"]
        await self.send_json({"type": "chat.event", "action": action, **response})

    async def agent_event(self, event: dict[str, Any]) -> None:
        """Forward server-produced commands or chat events to this tab's browser."""
        # Publishers use group_send(group, {"type": "agent.event", "payload": ...}).
        await self.send_json(event["payload"])
