"""Check lossless model-facing deduplication without changing durable MCP responses."""

import json
from copy import deepcopy
from unittest import TestCase
from uuid import uuid4

from bloomerp.agents.runtime import AgentRuntimeMessage
from bloomerp.agents.runtimes.pydantic_ai import _messages, _model_tool_result


class ToolResultProjectionTests(TestCase):
    """Cover structured mirrors, text fallback, multimodal content and replay."""

    def test_deduplicates_json_regardless_of_spacing_and_key_order(self) -> None:
        """Keep one structured representation and preserve the original audit payload."""
        original = {
            "structuredContent": {"name": "Résumé", "id": 42},
            "content": [
                {"type": "text", "text": '{ "id": 42, "name": "R\\u00e9sum\\u00e9" }'}
            ],
        }
        snapshot = deepcopy(original)
        projected = _model_tool_result(original)
        self.assertEqual(
            projected, {"structuredContent": original["structuredContent"]}
        )
        self.assertEqual(original, snapshot)
        self.assertLess(len(json.dumps(projected)), len(json.dumps(original)))

    def test_preserves_distinct_text_media_and_error_metadata(self) -> None:
        """Remove only the mirror, leaving warnings, media, annotations and error status intact."""
        extras = [
            {"type": "text", "text": "Only partial results are available."},
            {"type": "image", "data": "image-bytes", "mimeType": "image/png"},
            {
                "type": "resource",
                "resource": {"uri": "example://result", "text": "details"},
            },
            {"type": "text", "text": "{}", "annotations": {"audience": ["user"]}},
        ]
        original = {
            "structuredContent": {},
            "content": [{"type": "text", "text": "{}"}, *extras],
            "isError": True,
            "_meta": {"request": "one"},
        }
        self.assertEqual(_model_tool_result(original), {**original, "content": extras})

    def test_text_only_and_non_mcp_results_are_unchanged(self) -> None:
        """Keep fallback text and arbitrary tool outputs in their existing format."""
        for original in [
            None,
            {"value": 42},
            {"content": [{"type": "text", "text": "Answer"}]},
            {"structuredContent": None, "content": []},
        ]:
            with self.subTest(original=original):
                self.assertEqual(_model_tool_result(original), original)

    def test_does_not_confuse_distinct_json_values(self) -> None:
        """Preserve nonidentical JSON and malformed text instead of guessing equivalence."""
        for text in ['{"value":1}', '{"value":false}', "not JSON"]:
            original = {
                "structuredContent": {"value": True},
                "content": [{"type": "text", "text": text}],
            }
            self.assertEqual(_model_tool_result(original), original)

    def test_replayed_tool_results_use_the_same_projection(self) -> None:
        """Keep call pairing and error flags while deduplicating portable history inputs."""
        result = {
            "structuredContent": {"value": 42},
            "content": [{"type": "text", "text": '{"value":42}'}],
        }
        call = AgentRuntimeMessage(
            role="assistant",
            message_id=uuid4(),
            sequence=1,
            content=(
                {
                    "type": "tool_call",
                    "provider_call_id": "call",
                    "tool_identifier": "lookup",
                    "arguments": {},
                },
            ),
        )
        message = AgentRuntimeMessage(
            role="tool",
            message_id=uuid4(),
            sequence=2,
            content=(
                {
                    "type": "tool_result",
                    "provider_call_id": "call",
                    "result": result,
                    "is_error": True,
                },
            ),
        )
        converted = _messages((call, message), [])
        returned = converted[1].parts[0]
        self.assertEqual(returned.tool_call_id, "call")
        self.assertEqual(
            returned.content,
            {"is_error": True, "result": {"structuredContent": {"value": 42}}},
        )
        self.assertIn("content", message.content[0].result)
