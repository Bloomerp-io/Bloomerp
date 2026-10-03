"""Exercise artifact adaptation without altering MCP contracts or repeating effects."""

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import TestCase, override_settings

from bloomerp.agents.artifacts.registry import AI_ARTIFACT_REGISTRY
from bloomerp.agents.controller import AgentChatRequest, AgentController
from bloomerp.agents.definition import AIArtifactToolResult
from bloomerp.agents.runtime import (
    AgentRuntimeToolOutcomeEvent,
    AgentRuntimeToolProposal,
)
from bloomerp.components.agents.render_artifact import render_artifact
from bloomerp.models.agents import AIArtifact, AIMessageArtifact, AIRun, AIToolCall
from bloomerp.tests.agents.test_controller import agent_test_config
from bloomerp.utils.models import model_name_plural_underline


@override_settings(BLOOMERP_CONFIG=agent_test_config())
class ArtifactAdapterTests(TestCase):
    """Check result matching, access, durable deduplication, history and rendering."""

    def setUp(self) -> None:
        """Create an offline run and a successful create result for a readable fixture object."""
        self.user = get_user_model().objects.create_user(
            username="artifact-owner", is_superuser=True
        )
        self.target = get_user_model().objects.create_user(username="artifact-target")
        self.request = HttpRequest()
        self.request.method = "GET"
        self.request.user = self.user
        self.resource = model_name_plural_underline(get_user_model())
        self.enterContext(
            patch(
                "bloomerp.views.api.generic.base.get_auto_api_models",
                return_value=[get_user_model()],
            )
        )
        submission = AgentController(self.user).accept_message(
            AgentChatRequest(content=[{"type": "text", "text": "Create a record"}])
        )
        self.run = AIRun.objects.get(pk=submission.run_id)
        self.attempt = self.run.create_attempt(
            execution_mode="inline",
            executor_id="test",
            lease_duration=timedelta(minutes=1),
        )
        self.arguments = {"resource": self.resource, "operation": "create", "data": {}}
        self.result = {
            "structuredContent": {
                "resource": self.resource,
                "operation": "create",
                "object": {get_user_model()._meta.pk.name: self.target.pk},
            }
        }
        self.tool, _dispatch = AIToolCall.prepare(
            self.run,
            self.attempt.lease_token,
            AgentRuntimeToolProposal(
                provider_call_id="create-1",
                tool_identifier="api_assistant_mutations",
                tool_version="1",
                arguments=self.arguments,
            ),
            requires_approval=False,
        )
        self.tool.complete(self.result, self.attempt.lease_token)

    def test_persist_once_and_restore_context(self) -> None:
        """Repeated adaptation preserves one artifact/card and the original MCP result."""
        first = AIArtifact.from_tool_result(
            self.tool, self.request, self.attempt.lease_token
        )
        second = AIArtifact.from_tool_result(
            self.tool, self.request, self.attempt.lease_token
        )
        self.assertEqual([item.pk for item in first], [item.pk for item in second])
        self.assertEqual(AIArtifact.objects.count(), 1)
        self.assertEqual(AIMessageArtifact.objects.count(), 1)
        self.tool.refresh_from_db()
        self.assertEqual(self.tool.result, self.result)
        snapshot = self.run.conversation.transcript_page()
        self.assertEqual(
            snapshot["messages"][-1]["artifacts"][0]["id"], str(first[0].pk)
        )
        messages = self.run.conversation.messages_to_runtime_messages()
        self.assertIn(str(first[0].pk), messages[-1].content[0].text)
        event = self.run.apply_runtime_event(
            AgentRuntimeToolOutcomeEvent(
                run_id=self.run.pk,
                attempt_id=self.attempt.pk,
                outcome=self.tool.runtime_outcome(),
            ),
            lease_token=self.attempt.lease_token,
        )
        self.assertEqual(event.payload["data"]["artifacts"][0]["id"], str(first[0].pk))
        response = render_artifact(self.request, first[0].pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.target.pk), response.content.decode())

    def test_ignore_failed_update_and_unrelated_results(self) -> None:
        """Only matching successful creates yield artifacts, not queries or edits."""
        base = AIArtifactToolResult(
            tool_name="api_assistant_mutations",
            arguments=self.arguments,
            result=self.result,
        )
        for result in [
            base.model_copy(update={"tool_name": "query"}),
            base.model_copy(update={"result": {**self.result, "isError": True}}),
            base.model_copy(
                update={"arguments": {**self.arguments, "operation": "update"}}
            ),
        ]:
            self.assertEqual(
                list(AI_ARTIFACT_REGISTRY.adapt_tool_result(result, self.request)), []
            )

    def test_sql_query_is_attached_once_and_rendered_as_code(self) -> None:
        """A successful SQL call displays escaped SQL without repeating execution."""
        query = "SELECT '<script>alert(1)</script>' AS sample"
        tool, _dispatch = AIToolCall.prepare(
            self.run,
            self.attempt.lease_token,
            AgentRuntimeToolProposal(
                provider_call_id="sql-1",
                tool_identifier="api_sql_execute",
                tool_version="1",
                arguments={"query": query},
            ),
            requires_approval=False,
        )
        tool.complete(
            {"structuredContent": {"columns": ["sample"], "rows": []}},
            self.attempt.lease_token,
        )
        with patch("bloomerp.services.sql_services.SqlExecutor.execute_query") as execute:
            first = AIArtifact.from_tool_result(
                tool, self.request, self.attempt.lease_token
            )
            second = AIArtifact.from_tool_result(
                tool, self.request, self.attempt.lease_token
            )
            self.assertEqual([item.pk for item in first], [item.pk for item in second])
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0].kind, "sql_query")
            self.assertEqual(first[0].payload, {"query": query})
            self.assertEqual(AIMessageArtifact.objects.count(), 1)
            response = render_artifact(self.request, first[0].pk)
            self.assertContains(response, "<code>SELECT")
            self.assertContains(response, "&lt;script&gt;")
            self.assertNotContains(response, "<script>")
            execute.assert_not_called()

    def test_sql_query_adapter_ignores_failed_and_missing_queries(self) -> None:
        """Errors and absent or invalid SQL arguments do not produce query cards."""
        base = AIArtifactToolResult(
            tool_name="api_sql_execute",
            arguments={"query": "SELECT 1"},
            result={"structuredContent": {"rows": []}},
        )
        for result in [
            base.model_copy(update={"result": {"isError": True}}),
            base.model_copy(update={"arguments": {}}),
            base.model_copy(update={"arguments": {"query": "  "}}),
            base.model_copy(update={"arguments": {"query": 123}}),
        ]:
            with self.subTest(result=result):
                self.assertEqual(
                    list(AI_ARTIFACT_REGISTRY.adapt_tool_result(result, self.request)), []
                )

    def test_revoked_access_hides_card_and_context(self) -> None:
        """A previously created artifact cannot preserve read access after revocation."""
        artifact = AIArtifact.from_tool_result(
            self.tool, self.request, self.attempt.lease_token
        )[0]
        self.user.is_superuser = False
        self.user.save()
        self.run.conversation.owner = self.user
        response = render_artifact(self.request, artifact.pk)
        self.assertIn("Artifact unavailable", response.content.decode())
        self.assertNotIn(str(self.target.pk), response.content.decode())
        self.assertEqual(
            self.run.conversation.messages_to_runtime_messages()[-1].content[0].text,
            "Artifact unavailable.",
        )
        self.assertEqual(
            [
                item.pk
                for item in AIArtifact.from_tool_result(
                    self.tool, self.request, self.attempt.lease_token
                )
            ],
            [artifact.pk],
        )

    def test_foreign_conversation_cannot_render(self) -> None:
        """Artifact IDs are not sufficient to read another owner's attachment."""
        from django.http import Http404

        artifact = AIArtifact.from_tool_result(
            self.tool, self.request, self.attempt.lease_token
        )[0]
        self.request.user = self.target
        with self.assertRaises(Http404):
            render_artifact(self.request, artifact.pk)

    def test_adapter_failure_does_not_repeat_mutation(self) -> None:
        """A presentation error leaves the committed tool outcome reusable and unchanged."""
        from bloomerp.agents.mcp import McpToolCoordinator

        client = Mock()
        client.catalog.return_value = {
            "api_assistant_mutations": {
                "name": "api_assistant_mutations",
                "inputSchema": {},
            }
        }
        client.definition.return_value.version = "1"
        coordinator = McpToolCoordinator(self.run, self.attempt, client)
        proposal = AgentRuntimeToolProposal(
            provider_call_id="create-1",
            tool_identifier="api_assistant_mutations",
            tool_version="1",
            arguments=self.arguments,
        )
        with (
            patch.object(
                AIArtifact, "from_tool_result", side_effect=ValueError("bad adapter")
            ),
            self.assertLogs("bloomerp.agents.mcp", level="ERROR"),
        ):
            outcome = coordinator.execute(proposal)
        self.assertEqual(outcome.result, self.result)
        client.request.assert_not_called()
