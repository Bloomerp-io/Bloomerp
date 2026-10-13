"""Declarative lifecycle scenarios for AIArtifact persistence."""

from functools import partial
from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError

from bloomerp.models.agents import AIArtifact
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)

from ._fixtures import AgentModelFixtures


class TestAiartifactModel(AgentModelFixtures, BloomerpModelTestCase):
    """Exercise immutable revisions and typed analytics/form payloads."""

    model = AIArtifact

    def get_test_scenarios(self) -> list[ModelScenario[AIArtifact]]:
        """Declare independent artifact validation and revision expectations."""
        return self.with_agent_fixtures(
            [
                ModelScenario(
                    name="New chart revision preserves prior content",
                    create_args=self.revision_args,
                    create_validators=self.previous_revision_is_preserved,
                ),
                ModelScenario(
                    name="Stored chart payload is immutable",
                    create_args=self.chart_args,
                    update_args={
                        "payload": {
                            "kind": "analytics",
                            "config": {"query": "SELECT 2", "type": "table"},
                        }
                    },
                    expected_exceptions=[
                        ExpectedModelException("update", ValidationError, "immutable")
                    ],
                ),
                ModelScenario(
                    name="Revisions cannot cross conversations",
                    create_args=self.foreign_revision_args,
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "conversation"
                        )
                    ],
                ),
                ModelScenario(
                    name="Analytics payload requires a query",
                    create_args=partial(
                        self.chart_args,
                        payload={
                            "kind": "analytics",
                            "config": {"type": "table"},
                        },
                    ),
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError)
                    ],
                ),
                ModelScenario(
                    name="Artifact and payload kinds must match",
                    create_args=partial(self.chart_args, kind="form_patch"),
                    expected_exceptions=[
                        ExpectedModelException("create", ValidationError, "kind")
                    ],
                ),
                ModelScenario(
                    name="File artifact requires a binary reference",
                    create_args=partial(
                        self.chart_args, kind="file", payload={"kind": "file"}
                    ),
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "FileNode reference"
                        )
                    ],
                ),
                ModelScenario(
                    name="Form patch retains expected revision",
                    create_args=self.form_patch_args,
                    create_validators=self.form_revision_is_preserved,
                ),
                ModelScenario(
                    name="Form patch cannot write a field twice",
                    create_args=self.duplicate_patch_args,
                    expected_exceptions=[
                        ExpectedModelException(
                            "create", ValidationError, "unique field"
                        )
                    ],
                ),
            ]
        )

    def revision_args(self) -> dict[str, Any]:
        """Create a predecessor for a new artifact in the same conversation."""
        self.previous_revision = self.make_chart()
        return self.chart_args(previous_revision=self.previous_revision)

    def foreign_revision_args(self) -> dict[str, Any]:
        """Point a new artifact at a predecessor owned by another conversation."""
        return self.revision_args() | {"conversation": self.other_conversation}

    def previous_revision_is_preserved(self, artifact: AIArtifact) -> bool:
        """Verify revision identity and the unmodified predecessor's query."""
        self.previous_revision.refresh_from_db()
        return (
            artifact.previous_revision_id == self.previous_revision.pk
            and self.previous_revision.payload["config"]["query"]
            == "SELECT 1 AS revenue"
        )

    def form_patch_args(self) -> dict[str, Any]:
        """Bind a draft field update to an exact form revision and browser target."""
        return {
            "conversation": self.conversation,
            "kind": "form_patch",
            "payload": {
                "kind": "form_patch",
                "target_model": "crm.Customer",
                "form_id": "customer-edit",
                "tab_id": str(uuid4()),
                "page_id": "page-1",
                "expected_revision": 3,
                "values": [{"field": "name", "value": "Example"}],
            },
        }

    def duplicate_patch_args(self) -> dict[str, Any]:
        """Create an ambiguous patch proposing two values for one field."""
        values = self.form_patch_args()
        values["payload"]["values"].append({"field": "name", "value": "Other"})
        return values

    def form_revision_is_preserved(self, artifact: AIArtifact) -> bool:
        """Check the persisted patch still targets the requested form revision."""
        return artifact.payload["expected_revision"] == 3
