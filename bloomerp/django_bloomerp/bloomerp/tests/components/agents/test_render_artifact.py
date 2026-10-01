"""Scenario-based authorization checks for the generic artifact component."""

from django.contrib.auth import get_user_model

from bloomerp.models.agents import AIArtifact, AIConversation
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestRenderArtifact(BloomerpComponentTestCase):
    """Exercise the actual routed artifact endpoint and its method/ownership gates."""

    view_name = "components_render_agent_artifact"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Prepare a readable object reference and verify owner-only component access."""
        owner = get_user_model().objects.create_user(
            username="component-artifact-owner", is_superuser=True
        )
        other = get_user_model().objects.create_user(
            username="component-artifact-other"
        )
        conversation = AIConversation.objects.create(owner=owner)
        artifact = AIArtifact.objects.create(
            conversation=conversation,
            kind="object",
            payload={"model_label": owner._meta.label, "object_id": str(other.pk)},
        )
        kwargs = {"artifact_id": artifact.pk}
        return [
            RequestScenario(
                name="Owner renders",
                user=owner,
                view_kwargs=kwargs,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=self.contains_text(str(other.pk)),
                ),
            ),
            RequestScenario(
                name="Other user denied",
                user=other,
                view_kwargs=kwargs,
                expected=ExpectedResult(status_code=404),
            ),
            RequestScenario(
                name="Anonymous login required",
                view_kwargs=kwargs,
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="Read-only rendering",
                user=owner,
                method="POST",
                view_kwargs=kwargs,
                expected=ExpectedResult(status_code=405),
            ),
        ]
