"""Generated conversation contracts remain identical through the real MCP transport."""

from django.http import HttpResponse
from django.test import override_settings

from bloomerp.models.agents import AIConversation, AIMessage
from bloomerp.tests.agents.test_controller import agent_test_config
from bloomerp.tests.api.test_agent_conversation_access import ConversationFixtures
from bloomerp.tests.base import (
    BloomerpMcpViewTestCase,
    ExpectedResult,
    McpRequestScenario,
)


@override_settings(BLOOMERP_CONFIG=agent_test_config())
class TestAgentConversationMCP(ConversationFixtures, BloomerpMcpViewTestCase):
    """Cover creation, retrieval, field forgery and unrelated tool boundaries."""

    view_name = "api_assistant_mutations"

    def setUp(self) -> None:
        """Create private conversation fixtures for the standard MCP actors."""
        from bloomerp.management.commands.save_application_fields import Command

        super().setUp()
        Command().handle(suppress_output=True)
        self.extendedSetup()

    def get_test_scenarios(self) -> list[McpRequestScenario]:
        """Call actual registered MCP tools as an authenticated non-staff member."""
        return [
            McpRequestScenario(
                name="Create owned conversation over MCP",
                user=self.normal_user,
                arguments={
                    "model_label": "bloomerp.AIConversation",
                    "operation": "create",
                    "data": {"title": "MCP conversation"},
                },
                expected=ExpectedResult(response_validators=self.conversation_created),
            ),
            McpRequestScenario(
                name="Send user message over MCP",
                user=self.normal_user,
                arguments={
                    "model_label": "bloomerp.AIMessage",
                    "operation": "create",
                    "data": {
                        "conversation": str(self.own.pk),
                        "content_blocks": [{"type": "text", "text": "MCP hello"}],
                    },
                },
                expected=ExpectedResult(response_validators=self.message_created),
            ),
            McpRequestScenario(
                name="Reject forged assistant message over MCP",
                user=self.normal_user,
                arguments={
                    "model_label": "bloomerp.AIMessage",
                    "operation": "create",
                    "data": {
                        "conversation": str(self.own.pk),
                        "role": "assistant",
                        "content_blocks": [],
                    },
                },
                expected=ExpectedResult(response_validators=self.mcp_is_error()),
            ),
            McpRequestScenario(
                name="Reject foreign transcript retrieval",
                user=self.normal_user,
                view_name="api_assistant_object_retrieve",
                arguments={
                    "model_label": "bloomerp.AIMessage",
                    "object_id": str(self.foreign_message.pk),
                },
                expected=ExpectedResult(response_validators=self.mcp_is_error()),
            ),
            McpRequestScenario(
                name="Retrieve owned transcript entry",
                user=self.normal_user,
                view_name="api_assistant_object_retrieve",
                arguments={
                    "model_label": "bloomerp.AIMessage",
                    "object_id": str(self.own_message.pk),
                },
                expected=ExpectedResult(response_validators=self.mcp_is_error(False)),
            ),
            McpRequestScenario(
                name="Grant does not enable agent configuration",
                user=self.normal_user,
                arguments={
                    "model_label": "bloomerp.AIAgent",
                    "operation": "create",
                    "data": {"name": "Forbidden"},
                },
                expected=ExpectedResult(response_validators=self.mcp_is_error()),
            ),
            McpRequestScenario(
                name="Grant does not enable project mutations",
                user=self.normal_user,
                arguments={
                    "model_label": "bloomerp.Todo",
                    "operation": "create",
                    "data": {"title": "Forbidden"},
                },
                expected=ExpectedResult(response_validators=self.mcp_is_error()),
            ),
            McpRequestScenario(
                name="Grant does not bypass SQL staff restriction",
                user=self.normal_user,
                view_name="api_sql_execute",
                arguments={"query": "SELECT id FROM bloomerp_ai_conversation"},
                expected=ExpectedResult(response_validators=self.mcp_is_error()),
            ),
            McpRequestScenario(
                name="Anonymous cannot create conversation",
                arguments={
                    "model_label": "bloomerp.AIConversation",
                    "operation": "create",
                    "data": {},
                },
                expected=ExpectedResult(status_code=401),
            ),
        ]

    def conversation_created(self, response: HttpResponse) -> bool:
        """Check MCP delegation used the same server-owned creation contract."""
        result = response.json()["result"]
        self.assertFalse(result.get("isError"), result)
        if result.get("isError"):
            return False
        row = AIConversation.objects.get(pk=result["structuredContent"]["object"]["id"])
        return row.owner_id == self.normal_user.pk

    def message_created(self, response: HttpResponse) -> bool:
        """Check MCP sends only a user message and creates a separately owned run."""
        result = response.json()["result"]
        self.assertFalse(result.get("isError"), result)
        if result.get("isError"):
            return False
        row = AIMessage.objects.get(pk=result["structuredContent"]["object"]["id"])
        return (
            row.role == "user"
            and row.triggered_runs.get().initiated_by_id == self.normal_user.pk
        )
