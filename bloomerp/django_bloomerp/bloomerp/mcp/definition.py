from collections.abc import Callable
from copy import deepcopy
import re
from typing import Any, TypeAlias
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


McpSchema: TypeAlias = dict[str, Any]
McpSchemaFactory: TypeAlias = Callable[[], McpSchema]
McpSchemaSource: TypeAlias = McpSchema | McpSchemaFactory

RESOURCE_VARIABLE_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def validate_resource_uri(uri: str) -> str:
    """Require an absolute URI without whitespace, malformed escapes, or template syntax."""
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", uri):
        raise ValueError("MCP resource URIs must include a scheme")
    if re.search(r'[\s\x00-\x1f\x7f{}<>"\\]', uri) or re.search(r"%(?![0-9A-Fa-f]{2})", uri):
        raise ValueError("Invalid MCP resource URI")
    urlsplit(uri)
    return uri


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


class McpResourceMetadata(BaseModel):
    """Share content metadata between concrete and parameterized MCP resources."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    mime_type: str = Field(default="text/plain", min_length=1)


class McpResource(McpResourceMetadata):
    """Expose a router reader under one concrete resource URI."""

    uri: str = Field(min_length=1)

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        """Validate the public resource address at registration time."""
        return validate_resource_uri(value)


class McpResourceTemplate(McpResourceMetadata):
    """Expose a reader using simple, single-segment RFC 6570 `{name}` variables."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, arbitrary_types_allowed=True)
    uri_template: str = Field(min_length=1)
    parameter_schema: McpSchemaSource | None = Field(default=None, exclude=True)

    @field_validator("uri_template")
    @classmethod
    def validate_template(cls, value: str) -> str:
        """Reject unsupported expressions, repeated variables, and invalid literal URIs."""
        variables = RESOURCE_VARIABLE_PATTERN.findall(value)
        if not variables or len(variables) != len(set(variables)):
            raise ValueError("Resource templates require unique named variables")
        if "request" in variables:
            raise ValueError("Resource template variable 'request' is reserved")
        if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
            raise ValueError("Resource templates require a literal URI scheme")
        validate_resource_uri(RESOURCE_VARIABLE_PATTERN.sub("value", value))
        return value

    @property
    def identity(self) -> str:
        """Normalize variable names when detecting equivalent template registrations."""
        return RESOURCE_VARIABLE_PATTERN.sub("{}", self.uri_template)

    def match_uri(self, uri: str) -> dict[str, str] | None:
        """Extract decoded string arguments without permitting segment or path traversal."""
        parts: list[str] = []
        position = 0
        for variable in RESOURCE_VARIABLE_PATTERN.finditer(self.uri_template):
            parts.append(re.escape(self.uri_template[position:variable.start()]))
            parts.append(f"(?P<{variable.group(1)}>[^/?#]+)")
            position = variable.end()
        parts.append(re.escape(self.uri_template[position:]))
        match = re.fullmatch("".join(parts), uri)
        if match is None:
            return None
        arguments = {name: unquote(value, errors="strict") for name, value in match.groupdict().items()}
        for value in arguments.values():
            if value in {".", ".."} or re.search(r"[/\\\x00-\x1f\x7f]", value):
                raise ValueError("Invalid resource template argument")
        return arguments

    def get_parameter_schema(self) -> McpSchema:
        """Return argument validation for URI strings, or a supplied schema factory."""
        if self.parameter_schema is not None:
            return McpTool._resolve_schema(self.parameter_schema)
        names = RESOURCE_VARIABLE_PATTERN.findall(self.uri_template)
        return {
            "type": "object", "additionalProperties": False,
            "properties": {name: {"type": "string", "minLength": 1} for name in names},
            "required": names,
        }


McpContract: TypeAlias = McpTool | McpResource | McpResourceTemplate
