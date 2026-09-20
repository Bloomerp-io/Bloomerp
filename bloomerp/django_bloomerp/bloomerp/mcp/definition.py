from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


McpSchema: TypeAlias = dict[str, Any]
McpSchemaFactory: TypeAlias = Callable[[], McpSchema]
McpSchemaSource: TypeAlias = McpSchema | McpSchemaFactory


class McpTool(BaseModel):
    """MCP-specific metadata attached to a registered Bloomerp route.

    The route supplies the tool's identity and executable view. This contract
    only provides optional MCP-facing display overrides, structured input and
    output, and behavioural hints for that route.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

    title: str | None = Field(
        default=None,
        min_length=1,
        description="Optional human-readable name for client interfaces.",
    )
    description: str | None = Field(
        default=None,
        min_length=1,
        description="Model-facing guidance describing when and how to use the tool.",
    )
    input_schema: McpSchemaSource | None = Field(
        default=None,
        exclude=True,
        description="JSON Schema, or a factory returning it, for tool arguments.",
    )
    output_schema: McpSchemaSource | None = Field(
        default=None,
        exclude=True,
        description="Optional JSON Schema, or factory, for structured tool output.",
    )

    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    @model_validator(mode="after")
    def validate_annotations(self):
        if self.read_only_hint is True and self.destructive_hint is True:
            raise ValueError(
                "A read-only MCP tool cannot also be marked as destructive"
            )
        return self

    def get_input_schema(self) -> dict[str, Any]:
        """Return the JSON Schema advertised as the tool's ``inputSchema``."""
        if self.input_schema is None:
            return {"type": "object", "additionalProperties": False}
        return self._resolve_schema(self.input_schema)

    def get_output_schema(self) -> dict[str, Any] | None:
        """Return the optional JSON Schema advertised as ``outputSchema``."""
        if self.output_schema is None:
            return None
        return self._resolve_schema(self.output_schema)

    @staticmethod
    def _resolve_schema(source: McpSchemaSource) -> McpSchema:
        schema = source() if callable(source) else source
        if not isinstance(schema, dict):
            raise TypeError("An MCP schema factory must return a dictionary")
        return deepcopy(schema)

    def get_annotations(self) -> dict[str, bool]:
        """Return explicitly configured annotations using MCP field names."""
        annotations = {
            "readOnlyHint": self.read_only_hint,
            "destructiveHint": self.destructive_hint,
            "idempotentHint": self.idempotent_hint,
            "openWorldHint": self.open_world_hint,
        }
        return {
            name: value
            for name, value in annotations.items()
            if value is not None
        }
