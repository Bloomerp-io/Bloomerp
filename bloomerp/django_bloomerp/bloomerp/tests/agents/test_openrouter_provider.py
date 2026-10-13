"""Test the additive OpenRouter integration with mocked HTTP, never a live API key."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openrouter import OpenRouterModel

from bloomerp.agents.providers.builtins.pydantic_ai_common import PydanticAISettings
from bloomerp.agents.providers.builtins.pydantic_openrouter import (
    create_openrouter_model,
)
from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY, provider_choices
from bloomerp.agents.runtime import (
    AgentRuntimeConfig,
    AgentRuntimeCredentials,
    AgentRuntimeEvent,
    AgentRuntimeRunRequest,
)
from bloomerp.agents.runtimes.pydantic_ai import PydanticAIRuntime, create_model
from bloomerp.tests.agents.test_pydantic_ai import Coordinator


class Answer(BaseModel):
    """Describe a small structured response for the SDK compatibility check."""

    value: int


class OpenRouterProviderTests(IsolatedAsyncioTestCase):
    """Exercise a specialized SDK boundary outside Django request scenarios."""

    def setUp(self) -> None:
        """Prepare a registered provider request and capture outbound mock traffic."""
        self.request = AgentRuntimeRunRequest(
            run_id=uuid4(),
            attempt_id=uuid4(),
            config=AgentRuntimeConfig(
                runtime="pydantic_ai",
                provider="openrouter",
                model="openai/gpt-4.1-mini",
                agent_key="bloomai",
                agent_version="1",
                request_timeout_seconds=17,
                parameters={"temperature": 0.2, "max_tokens": 123},
            ),
            context={"user_id": "1", "conversation_id": uuid4()},
            messages=(
                {
                    "role": "user",
                    "message_id": uuid4(),
                    "sequence": 1,
                    "content": [{"type": "text", "text": "Look it up"}],
                },
            ),
        )
        self.credentials = AgentRuntimeCredentials(api_key="mock-openrouter-key")
        self.requests: list[httpx.Request] = []

    def test_registration_reuses_existing_contract_without_discovery(self) -> None:
        """Expose a distinct selectable provider without a discovery callback or adapter."""
        registration = AI_PROVIDER_REGISTRY.get("openrouter")
        self.assertEqual(registration.name, "OpenRouter")
        self.assertIs(registration.config_schema, PydanticAISettings)
        self.assertIs(registration.integration.factory, create_openrouter_model)
        self.assertIsNone(registration.model_identifier_factory)
        self.assertIn(("openrouter", "OpenRouter"), provider_choices())
        self.assertIsInstance(
            registration.runtime_factory(self.request.config), PydanticAIRuntime
        )
        for existing in ("openai", "openai_chat", "anthropic", "deepseek"):
            with self.subTest(provider=existing):
                self.assertIsNotNone(AI_PROVIDER_REGISTRY.get(existing))

    async def test_model_endpoint_credentials_and_client_are_explicit(self) -> None:
        """Keep vendor IDs, configured endpoints, explicit credentials and client ownership."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "ambient-openai-key",
                "OPENROUTER_API_KEY": "ambient-router-key",
                "OPENAI_BASE_URL": "https://ambient.example.invalid/v1",
                "OPENROUTER_APP_URL": "https://ambient.example.invalid",
            },
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(self.structured_response)
            ) as client:
                for model_id in (
                    "openai/gpt-4.1-mini",
                    "anthropic/claude-sonnet-4",
                    "vendor/custom-model:free",
                ):
                    with self.subTest(model=model_id):
                        request = self.request.model_copy(
                            update={
                                "config": self.request.config.model_copy(
                                    update={"model": model_id}
                                )
                            }
                        )
                        model = create_model(request, self.credentials, client)
                        self.assertIsInstance(model, OpenRouterModel)
                        self.assertEqual(model.system, "openrouter")
                        self.assertEqual(model.model_name, model_id)
                        self.assertEqual(
                            str(model.client.base_url), "https://openrouter.ai/api/v1/"
                        )
                        self.assertEqual(model.client.api_key, "mock-openrouter-key")
                        self.assertIs(model.client._client, client)
                        self.assertEqual(model.client.max_retries, 0)
                        self.assertNotIn("HTTP-Referer", model.client.default_headers)
                request = self.request.model_copy(
                    update={
                        "config": self.request.config.model_copy(
                            update={"base_url": "https://gateway.example.test/v1"}
                        )
                    }
                )
                model = create_model(request, self.credentials, client)
                self.assertEqual(
                    str(model.client.base_url), "https://gateway.example.test/v1/"
                )

    async def test_missing_credentials_do_not_fall_back_to_environment(self) -> None:
        """Give a provider-specific configuration error rather than use ambient secrets."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "ambient-key"}):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(self.structured_response)
            ) as client:
                for credentials in (
                    AgentRuntimeCredentials(),
                    AgentRuntimeCredentials(api_key=""),
                ):
                    with (
                        self.subTest(credentials=credentials),
                        self.assertRaisesRegex(
                            ValueError, "OpenRouter requires an API key"
                        ),
                    ):
                        create_model(self.request, credentials, client)

    async def test_model_identifier_error_is_actionable(self) -> None:
        """Reject incomplete identifiers before the SDK tries to choose a vendor profile."""
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(self.structured_response)
        ) as client:
            for model_id in ("gpt-4.1-mini", "/model", "openai/", " /model"):
                with self.subTest(model=model_id):
                    request = self.request.model_copy(
                        update={
                            "config": self.request.config.model_copy(
                                update={"model": model_id}
                            )
                        }
                    )
                    with self.assertRaisesRegex(ValueError, "vendor/model"):
                        create_model(request, self.credentials, client)

    async def test_existing_settings_validation_remains_in_force(self) -> None:
        """Retain the shared allow-list without introducing arbitrary provider request bodies."""
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(self.structured_response)
        ) as client:
            for parameters in (
                {"temperature": 3},
                {"extra_body": {"api_key": "not-allowed"}},
            ):
                with self.subTest(parameters=parameters):
                    request = self.request.model_copy(
                        update={
                            "config": self.request.config.model_copy(
                                update={"parameters": parameters}
                            )
                        }
                    )
                    with self.assertRaises(ValidationError):
                        create_model(request, self.credentials, client)

    def stream_response(self, request: httpx.Request) -> httpx.Response:
        """Return a tool request, then a text response using OpenRouter's SSE envelope."""
        self.requests.append(request)
        first_round = len(self.requests) == 1
        delta: dict[str, Any] = (
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"key":"answer"}'},
                    }
                ],
            }
            if first_round
            else {"role": "assistant", "content": "The answer is 42."}
        )
        chunk = {
            "id": f"gen-mock-{len(self.requests)}",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": self.request.config.model,
            "provider": "OpenAI",
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": None,
                    "native_finish_reason": None,
                }
            ],
        }
        end = chunk | {
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "tool_calls" if first_round else "stop",
                    "native_finish_reason": "tool_calls" if first_round else "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        content = (
            "".join(f"data: {json.dumps(item)}\n\n" for item in (chunk, end))
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, text=content
        )

    async def collect_runtime(
        self, client: httpx.AsyncClient
    ) -> list[AgentRuntimeEvent]:
        """Run the unchanged runtime and registered factory against an owned mocked client."""
        request = AgentRuntimeRunRequest.model_validate(
            self.request.model_dump()
            | {
                "tools": (
                    {
                        "identifier": "lookup",
                        "version": "1",
                        "description": "Look up a value",
                        "input_schema": {
                            "type": "object",
                            "properties": {"key": {"type": "string"}},
                            "required": ["key"],
                            "additionalProperties": False,
                        },
                    },
                )
            }
        )
        coordinator = Coordinator()
        runtime = PydanticAIRuntime()
        try:
            with patch(
                "bloomerp.agents.runtimes.pydantic_ai.httpx",
                SimpleNamespace(
                    AsyncClient=Mock(return_value=client),
                    TimeoutException=httpx.TimeoutException,
                ),
            ):
                events = [
                    event
                    async for event in runtime.execute(
                        request, credentials=self.credentials, coordinator=coordinator
                    )
                ]
        finally:
            await runtime.aclose()
        self.coordinator = coordinator
        return events

    async def test_registered_provider_streams_tools_and_preserves_settings(
        self,
    ) -> None:
        """Exercise real SDK serialization, streamed tool dispatch, settings and final text."""
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.stream_response))
        events = await self.collect_runtime(client)
        self.assertEqual(events[-1].kind, "run.completed", events[-1])
        self.assertEqual(
            "".join(event.text for event in events if event.kind == "text.delta"),
            "The answer is 42.",
        )
        self.assertEqual(len(self.coordinator.calls), 1)
        self.assertEqual(self.coordinator.calls[0].arguments, {"key": "answer"})
        self.assertEqual(events[-1].usage.tool_calls, 1)
        self.assertTrue(client.is_closed)
        self.assertEqual(len(self.requests), 2)
        for request in self.requests:
            body = json.loads(request.content)
            self.assertEqual(
                str(request.url), "https://openrouter.ai/api/v1/chat/completions"
            )
            self.assertEqual(
                request.headers["authorization"], "Bearer mock-openrouter-key"
            )
            self.assertEqual(body["model"], "openai/gpt-4.1-mini")
            self.assertEqual(body["temperature"], 0.2)
            self.assertEqual(body["max_completion_tokens"], 123)
            self.assertTrue(body["stream"])
            self.assertEqual(request.extensions["timeout"]["read"], 17)
        second_body = json.loads(self.requests[1].content)
        tool_result = next(
            message for message in second_body["messages"] if message["role"] == "tool"
        )
        self.assertEqual(json.loads(tool_result["content"]), {"value": 42})
        self.assertNotIn(
            "mock-openrouter-key", "".join(event.model_dump_json() for event in events)
        )

    def structured_response(self, request: httpx.Request) -> httpx.Response:
        """Return one schema-shaped response without contacting OpenRouter."""
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "gen-structured",
                "object": "chat.completion",
                "created": 1,
                "model": self.request.config.model,
                "provider": "OpenAI",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"value":42}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    async def test_sdk_structured_output_remains_available_for_compatible_models(
        self,
    ) -> None:
        """Verify JSON-schema output passes through the existing installed SDK model."""
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(self.structured_response)
        ) as client:
            model = create_model(self.request, self.credentials, client)
            result = await Agent(model, output_type=NativeOutput(Answer)).run(
                "Return 42"
            )
        self.assertEqual(result.output.value, 42)
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertEqual(
            body["response_format"]["json_schema"]["schema"]["properties"]["value"][
                "type"
            ],
            "integer",
        )

    async def test_provider_rejections_remain_safe_failures_without_sdk_retries(
        self,
    ) -> None:
        """Keep unsupported requests and provider errors distinct from successful completion."""
        for status, retryable in ((400, False), (401, False), (429, True), (503, True)):
            with self.subTest(status=status):
                requests: list[httpx.Request] = []

                def reject(
                    request: httpx.Request,
                    status: int = status,
                    requests: list[httpx.Request] = requests,
                ) -> httpx.Response:
                    """Emulate a provider rejection containing text that must not be exposed."""
                    requests.append(request)
                    return httpx.Response(
                        status,
                        json={
                            "error": {
                                "message": "mock-openrouter-key: model does not support tools",
                                "code": status,
                            }
                        },
                    )

                client = httpx.AsyncClient(transport=httpx.MockTransport(reject))
                events = await self.collect_runtime(client)
                self.assertEqual(events[-1].kind, "run.failed", events[-1])
                self.assertEqual(events[-1].error.code, "provider_error")
                self.assertEqual(events[-1].error.retryable, retryable)
                self.assertEqual(len(requests), 1)
                self.assertEqual(self.coordinator.calls, [])
                self.assertNotIn(
                    "mock-openrouter-key",
                    "".join(event.model_dump_json() for event in events),
                )
