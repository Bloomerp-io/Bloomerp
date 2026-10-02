from django.test import SimpleTestCase
from pydantic import ValidationError

from bloomerp.mcp.definition import McpTool


SEARCH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}
SEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {"type": "string"}}},
}


class McpToolTests(SimpleTestCase):
    def test_defines_typed_tool_contract(self):
        tool = McpTool(
            title="Search customers",
            description="Search customers by name.",
            input_schema=SEARCH_INPUT_SCHEMA,
            output_schema=lambda: SEARCH_OUTPUT_SCHEMA,
            read_only_hint=True,
            open_world_hint=False,
        )

        self.assertEqual(tool.get_input_schema(), SEARCH_INPUT_SCHEMA)
        self.assertEqual(tool.get_output_schema(), SEARCH_OUTPUT_SCHEMA)
        self.assertEqual(
            tool.get_annotations(),
            {"readOnlyHint": True, "openWorldHint": False},
        )

    def test_tool_without_input_schema_rejects_unspecified_arguments(self):
        tool = McpTool()

        self.assertEqual(
            tool.get_input_schema(),
            {"type": "object", "additionalProperties": False},
        )
        self.assertIsNone(tool.get_output_schema())

    def test_rejects_unknown_configuration(self):
        with self.assertRaises(ValidationError):
            McpTool(unsupported=True)

    def test_rejects_destructive_read_only_tool(self):
        with self.assertRaisesRegex(
            ValidationError,
            "read-only MCP tool cannot also be marked as destructive",
        ):
            McpTool(
                read_only_hint=True,
                destructive_hint=True,
            )

    def test_schema_results_do_not_mutate_the_definition(self):
        tool = McpTool(input_schema=SEARCH_INPUT_SCHEMA)

        tool.get_input_schema()["properties"]["query"]["type"] = "integer"

        self.assertEqual(
            tool.get_input_schema()["properties"]["query"]["type"],
            "string",
        )
