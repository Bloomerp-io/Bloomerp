"""Proposed tile artifact using the existing extensible workspace tile schemas."""

from typing import TYPE_CHECKING, Self

from pydantic import Field, JsonValue, model_validator

from bloomerp.agents.definition import (
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactTypeDefinition,
)

if TYPE_CHECKING:
    from bloomerp.workspaces.base import BaseTileConfig


class TileArtifactPayload(AIArtifactPayload):
    """Store a tile configuration independently of a saved workspace tile."""

    title: str = Field(min_length=1, max_length=255)
    tile_type: str = Field(min_length=1, max_length=255)
    config: dict[str, JsonValue]

    def get_config(self) -> "BaseTileConfig":
        """Validate against the registered tile schema without rendering or querying data."""
        from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY

        definition = TILE_TYPE_REGISTRY.get(self.tile_type)
        if definition is None or definition.model is None:
            raise ValueError(f"Unknown or unconfigured tile type: {self.tile_type}")
        return definition.model.model_validate(self.config)

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        """Reject configurations incompatible with their selected tile type."""
        self.get_config()
        return self


def describe_tile(payload: TileArtifactPayload) -> AIArtifactDescription:
    """Describe a saved configuration without executing its query or rendering HTML."""
    return AIArtifactDescription(
        title=payload.title,
        summary=f"Tile configuration ({payload.tile_type}); live data requires authorized rendering. This is not a data snapshot.",
    )


TILE_ARTIFACT = AIArtifactTypeDefinition[TileArtifactPayload](
    key="tile",
    label="Tile",
    model=TileArtifactPayload,
    describe=describe_tile,
    icon="fa-chart-line",
)
