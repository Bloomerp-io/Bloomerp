"""Proposed model artifact payload and registration, without I/O or execution wiring."""

from pydantic import Field

from bloomerp.agents.definition import (
    AIArtifactDescription,
    AIArtifactPayload,
    AIArtifactTypeDefinition,
)


class ModelArtifactPayload(AIArtifactPayload):
    """Identify a model source without copying its live content or permissions."""

    model_label: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*$")


def describe_model(payload: ModelArtifactPayload) -> AIArtifactDescription:
    """Describe the reference without fetching content or asserting target access."""
    return AIArtifactDescription(
        title=payload.model_label,
        summary=f"Reference to the {payload.model_label} model; schema and operations require authorized inspection.",
    )


MODEL_ARTIFACT = AIArtifactTypeDefinition[ModelArtifactPayload](
    key="model",
    label="Model",
    model=ModelArtifactPayload,
    describe=describe_model,
    icon="fa-table",
)
