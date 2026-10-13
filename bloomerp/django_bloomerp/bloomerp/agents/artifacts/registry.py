"""Versioned artifact registrations using BloomERP's shared registry pattern."""

from collections.abc import Iterator

from django.http import HttpRequest
from pydantic import JsonValue

from bloomerp.agents.definition import (
    AIArtifactCandidate,
    AIArtifactPayload,
    AIArtifactToolResult,
    AIArtifactTypeDefinition,
)
from bloomerp.utils.registry import BaseRegistry

from .file import FILE_ARTIFACT
from .mcp import MCP_ARTIFACT
from .model import MODEL_ARTIFACT
from .module import MODULE_ARTIFACT
from .object import OBJECT_ARTIFACT
from .sql_query import SQL_QUERY_ARTIFACT
from .tile import TILE_ARTIFACT


class AIArtifactRegistry(BaseRegistry[AIArtifactTypeDefinition]):
    """Keep independently registered schema versions available for stored artifacts."""

    def register(self, key: str, obj: AIArtifactTypeDefinition) -> None:
        """Register a logical type/version pair and reject conflicting identities."""
        if not isinstance(obj, AIArtifactTypeDefinition):
            raise TypeError("Object must be an AIArtifactTypeDefinition")
        if key != obj.key:
            raise ValueError("Registration key must match the artifact definition key")
        adapter_keys = [adapter.key for adapter in obj.tool_result_adapters]
        if len(adapter_keys) != len(set(adapter_keys)):
            raise ValueError("Adapter keys must be unique within an artifact type")
        super().register(self.version_key(key, obj.schema_version), obj)

    @staticmethod
    def version_key(key: str, schema_version: int) -> str:
        """Build the explicit storage key used by inherited get/unregister methods."""
        return f"{key}@{schema_version}"

    def get_type(self, key: str, schema_version: int = 1) -> AIArtifactTypeDefinition:
        """Resolve an exact version without silently falling back to a newer schema."""
        definition = self.get(self.version_key(key, schema_version))
        if definition is None:
            raise KeyError(f"Unknown artifact type/version: {key}@{schema_version}")
        return definition

    def validate_payload(
        self, key: str, schema_version: int, payload: dict[str, JsonValue]
    ) -> AIArtifactPayload:
        """Validate payload shape only; callers must separately authorize the source."""
        return self.get_type(key, schema_version).model.model_validate(payload)

    def adapt_tool_result(
        self, result: AIArtifactToolResult, request: HttpRequest
    ) -> Iterator[tuple[AIArtifactTypeDefinition, str, AIArtifactCandidate]]:
        """Dispatch by tool name and validate every candidate through its registered type."""
        if result.result.get("isError"):
            return
        latest = {}
        for definition in self.values():
            if (
                definition.key not in latest
                or definition.schema_version > latest[definition.key].schema_version
            ):
                latest[definition.key] = definition
        for definition in latest.values():
            for adapter in definition.tool_result_adapters:
                if result.tool_name not in adapter.tool_names:
                    continue
                candidates = adapter.adapt(result, request)
                if len(candidates) > 100:
                    raise ValueError(
                        "An adapter may return at most 100 artifacts per tool call"
                    )
                seen = set()
                for candidate in candidates:
                    if candidate.key in seen:
                        raise ValueError("Adapter candidate keys must be unique")
                    seen.add(candidate.key)
                    normalized = definition.model.model_validate(candidate.payload)
                    if definition.authorize is not None:
                        definition.authorize(normalized, request)
                    yield (
                        definition,
                        adapter.key,
                        candidate.model_copy(
                            update={"payload": normalized.model_dump(mode="json")}
                        ),
                    )


AI_ARTIFACT_REGISTRY = AIArtifactRegistry(AIArtifactTypeDefinition)

AI_ARTIFACT_REGISTRY.register("file", FILE_ARTIFACT)
AI_ARTIFACT_REGISTRY.register("module", MODULE_ARTIFACT)
AI_ARTIFACT_REGISTRY.register("model", MODEL_ARTIFACT)
AI_ARTIFACT_REGISTRY.register("object", OBJECT_ARTIFACT)
AI_ARTIFACT_REGISTRY.register("sql_query", SQL_QUERY_ARTIFACT)
AI_ARTIFACT_REGISTRY.register("mcp", MCP_ARTIFACT)
AI_ARTIFACT_REGISTRY.register("tile", TILE_ARTIFACT)
