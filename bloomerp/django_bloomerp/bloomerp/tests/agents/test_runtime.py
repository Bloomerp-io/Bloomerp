"""Contract checks for provider-independent runtime requests and events."""

from copy import deepcopy
from typing import Any
from unittest import TestCase
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from bloomerp.agents.runtime import (
    AgentRuntimeCheckpoint,
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeEvent,
    AgentRuntimeMessage,
    AgentRuntimeResumeRequest,
    AgentRuntimeRunPausedEvent,
    AgentRuntimeRunRequest,
    AgentRuntimeToolOutcome,
)


class AgentRuntimeContractTests(TestCase):
    """Exercise boundaries that adapters and the durable runner must agree on."""

    def setUp(self) -> None:
        """Build a portable initial request with no Django or provider dependency."""
        self.config = AgentRuntimeConfig(
            runtime="pydantic_ai",
            provider="anthropic",
            model="instance-selected-model",
            agent_key="bloomai",
            agent_version="1",
        )
        self.request = AgentRuntimeRunRequest(
            run_id=uuid4(),
            attempt_id=uuid4(),
            config=self.config,
            context={
                "user_id": "user-1",
                "conversation_id": uuid4(),
            },
            messages=[
                {
                    "role": "user",
                    "message_id": uuid4(),
                    "sequence": 1,
                    "content": [
                        {"type": "text", "format": "html", "text": "<p>Hello</p>"}
                    ],
                }
            ],
        )
        self.checkpoint = AgentRuntimeCheckpoint(
            run_id=self.request.run_id,
            context=self.request.context,
            runtime=self.config.runtime,
            runtime_version="1",
            format_version=1,
            config_fingerprint=self.config.fingerprint(),
            consumed_message_sequence=1,
            state={"provider_history": [{"type": "opaque", "payload": "preserve-me"}]},
        )

    def resume_data(self) -> dict[str, Any]:
        """Prepare a new attempt with only new transcript input after the cursor."""
        run = self.request.model_dump(mode="json")
        run["attempt_id"] = str(uuid4())
        run["messages"] = [
            {
                "role": "user",
                "message_id": str(uuid4()),
                "sequence": 2,
                "content": [{"type": "text", "text": "Continue"}],
            }
        ]
        return {"run": run, "checkpoint": self.checkpoint.model_dump(mode="json")}

    def test_credentials_are_excluded_from_representation_and_serialization(
        self,
    ) -> None:
        """Keep instance API keys out of checkpoint and event serialization paths."""
        credentials = AgentRuntimeCredentials(api_key="private-test-key")
        self.assertNotIn("private-test-key", repr(credentials))
        self.assertEqual(credentials.model_dump(), {})
        self.assertEqual(credentials.model_dump_json(), "{}")
        self.assertEqual(credentials.api_key.get_secret_value(), "private-test-key")
        request = self.request.model_dump(mode="json")
        request["credentials"] = {"api_key": "private-test-key"}
        with self.assertRaises(ValidationError):
            AgentRuntimeRunRequest.model_validate(request)

    def test_provider_identifiers_are_extensible(self) -> None:
        """Accept supported and custom provider names without a hard-coded enum."""
        for provider in ("openai", "anthropic", "deepseek", "instance-custom"):
            with self.subTest(provider=provider):
                values = self.config.model_dump()
                values["provider"] = provider
                self.assertEqual(
                    AgentRuntimeConfig.model_validate(values).provider, provider
                )

    def test_configuration_round_trips_through_the_persistence_schema(self) -> None:
        """Persist endpoint settings without mixing runtime identity into the snapshot."""
        values = self.config.model_dump()
        values.update(
            base_url="https://provider.example/v1", request_timeout_seconds=90
        )
        config = AgentRuntimeConfig.model_validate(values)
        snapshot = config.to_snapshot()
        restored = AgentRuntimeConfig.model_validate(
            snapshot.model_dump(mode="json")
            | {"agent_key": config.agent_key, "agent_version": config.agent_version}
        )
        self.assertEqual(restored.fingerprint(), config.fingerprint())
        self.assertNotIn("agent_key", snapshot.model_dump())

    def test_structured_messages_support_artifacts_and_paired_tool_history(
        self,
    ) -> None:
        """Carry rich text, resolved artifacts, and matching provider call IDs."""
        attachment = AgentRuntimeMessage.model_validate(
            {
                "role": "user",
                "content": [
                    {"type": "text", "format": "markdown", "text": "Read **this**"},
                    {
                        "type": "artifact",
                        "artifact_id": str(uuid4()),
                        "media_type": "application/pdf",
                        "content": {"text": "Extracted invoice"},
                    },
                ],
            }
        )
        call = AgentRuntimeMessage.model_validate(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_call",
                        "provider_call_id": "call-1",
                        "tool_identifier": "query",
                        "arguments": {},
                    }
                ],
            }
        )
        result = AgentRuntimeMessage.model_validate(
            {
                "role": "tool",
                "content": [
                    {
                        "type": "tool_result",
                        "provider_call_id": "call-1",
                        "result": {"rows": []},
                    }
                ],
            }
        )
        self.assertEqual(attachment.content[1].media_type, "application/pdf")
        self.assertEqual(
            call.content[0].provider_call_id, result.content[0].provider_call_id
        )

    def test_message_provenance_and_tool_roles_are_validated(self) -> None:
        """Reject incomplete transcript identities and misplaced tool results."""
        for message in (
            {"role": "user", "sequence": 1, "content": []},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "provider_call_id": "x", "result": {}}
                ],
            },
            {"role": "tool", "content": [{"type": "text", "text": "unpaired"}]},
        ):
            with self.subTest(message=message), self.assertRaises(ValidationError):
                AgentRuntimeMessage.model_validate(message)

    def test_request_rejects_ambiguous_tools_and_duplicate_sequences(self) -> None:
        """Prevent ambiguous dispatch and replaying one transcript position twice."""
        values = self.request.model_dump(mode="json")
        tool = {
            "identifier": "query",
            "version": "1",
            "description": "Query",
            "input_schema": {"type": "object"},
        }
        values["tools"] = [tool, tool]
        with self.assertRaises(ValidationError):
            AgentRuntimeRunRequest.model_validate(values)
        values["tools"] = []
        values["messages"] *= 2
        with self.assertRaises(ValidationError):
            AgentRuntimeRunRequest.model_validate(values)

    def test_resume_round_trips_provider_state_under_a_new_attempt(self) -> None:
        """Restore exact opaque history without carrying old credentials or attempts."""
        resumed = AgentRuntimeResumeRequest.model_validate(self.resume_data())
        restored = AgentRuntimeResumeRequest.model_validate_json(
            resumed.model_dump_json()
        )
        self.assertEqual(restored.checkpoint.state, self.checkpoint.state)
        self.assertNotEqual(restored.run.attempt_id, self.request.attempt_id)
        self.assertEqual(restored.run.run_id, self.request.run_id)

    def test_resume_rejects_wrong_run_actor_and_configuration(self) -> None:
        """Keep checkpoint reuse bound to its original execution identity and settings."""
        base = self.resume_data()
        for section, key, value in (
            ("run", "run_id", str(uuid4())),
            ("context", "user_id", "another-user"),
            ("context", "conversation_id", str(uuid4())),
            ("config", "provider", "deepseek"),
            ("config", "model", "changed-model"),
            ("config", "runtime", "another-adapter"),
        ):
            data = deepcopy(base)
            target = data["run"] if section == "run" else data["run"][section]
            target[key] = value
            with (
                self.subTest(section=section, key=key),
                self.assertRaises(ValidationError),
            ):
                AgentRuntimeResumeRequest.model_validate(data)

    def test_resume_rejects_replayed_messages_and_untrusted_decisions(self) -> None:
        """Accept fresh transcript input while requiring persisted approval resolution."""
        data = self.resume_data()
        data["run"]["messages"][0]["sequence"] = 1
        with self.assertRaises(ValidationError):
            AgentRuntimeResumeRequest.model_validate(data)
        data = self.resume_data()
        data["decisions"] = [{"approved": True, "tool_call_id": str(uuid4())}]
        with self.assertRaises(ValidationError):
            AgentRuntimeResumeRequest.model_validate(data)

    def test_tool_outcomes_distinguish_waiting_results_and_failures(self) -> None:
        """Require enough durable information to resume a deferred action safely."""
        identity = {"tool_call_id": uuid4(), "provider_call_id": "call-1"}
        for values in (
            {"status": "completed", "result": {}},
            {"status": "waiting", "approval_ids": [uuid4()]},
            {"status": "failed", "error": {"code": "timeout", "message": "Timed out"}},
            {"status": "rejected", "error": {"code": "denied", "message": "Rejected"}},
        ):
            with self.subTest(status=values["status"]):
                AgentRuntimeToolOutcome.model_validate(identity | values)
        for values in (
            {"status": "completed"},
            {"status": "waiting"},
            {"status": "waiting", "approval_ids": [uuid4()], "result": {}},
            {"status": "failed", "result": {}},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                AgentRuntimeToolOutcome.model_validate(identity | values)

    def test_pause_event_round_trips_checkpoint_wait_and_usage(self) -> None:
        """Make the pause event sufficient to persist and release an execution attempt."""
        event = AgentRuntimeRunPausedEvent(
            run_id=self.request.run_id,
            attempt_id=self.request.attempt_id,
            checkpoint=self.checkpoint,
            wait_condition={"kind": "user_input"},
            usage={"input_tokens": 12},
        )
        restored = TypeAdapter(AgentRuntimeEvent).validate_json(event.model_dump_json())
        self.assertIsInstance(restored, AgentRuntimeRunPausedEvent)
        self.assertEqual(restored.checkpoint.state, self.checkpoint.state)
        self.assertEqual(restored.usage.input_tokens, 12)
        values = event.model_dump(mode="json")
        values["run_id"] = str(uuid4())
        with self.assertRaises(ValidationError):
            TypeAdapter(AgentRuntimeEvent).validate_python(values)

    def test_event_kind_requires_matching_payload(self) -> None:
        """Reject loosely typed event payloads that cannot be persisted reliably."""
        with self.assertRaises(ValidationError):
            TypeAdapter(AgentRuntimeEvent).validate_python(
                {
                    "kind": "text.delta",
                    "run_id": uuid4(),
                    "attempt_id": uuid4(),
                    "error": {"code": "x", "message": "wrong payload"},
                }
            )

    def test_pauses_require_a_resolvable_wake_condition(self) -> None:
        """Reject timers without a deadline and approvals without durable references."""
        base = {
            "run_id": self.request.run_id,
            "attempt_id": self.request.attempt_id,
            "checkpoint": self.checkpoint,
            "usage": {},
        }
        for kind in ("timer", "approval"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                AgentRuntimeRunPausedEvent.model_validate(
                    base | {"wait_condition": {"kind": kind}}
                )
        timer = AgentRuntimeRunPausedEvent.model_validate(
            base
            | {
                "wait_condition": {"kind": "timer"},
                "resume_after": "2026-10-01T12:00:00Z",
            }
        )
        self.assertIsNotNone(timer.resume_after.tzinfo)
