"""Scenarios for the consolidated field-visibility action."""

from bloomerp.form_behaviors.builtins.set_field_visibility import (
    SET_FIELD_VISIBILITY,
)
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorResult,
    FieldStateUpdate,
)
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase


class TestSetFieldVisibilityAction(BloomerpBehaviorActionTestCase):
    """Verify both visibility states leave interaction and values untouched."""

    action = SET_FIELD_VISIBILITY

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Return visible and hidden outcomes for one declared target."""
        listener = self.get_application_field("first_name")
        target = self.get_application_field("last_name")
        context = BehaviorContext(
            values={"first_name": "Ada", "last_name": "Lovelace"},
            listener_field="first_name",
            target_field="last_name",
        )
        return [
            BehaviorActionScenario(
                name="Show the target without changing its interaction state",
                context=context,
                listener=listener,
                target=target,
                config={"visibility": "visible"},
                expected_result=BehaviorResult(
                    states=(FieldStateUpdate(field="last_name", visible=True),)
                ),
            ),
            BehaviorActionScenario(
                name="Hide the target without changing its interaction state",
                context=context,
                listener=listener,
                target=target,
                config={"visibility": "hidden"},
                expected_result=BehaviorResult(
                    states=(FieldStateUpdate(field="last_name", visible=False),)
                ),
            ),
        ]

