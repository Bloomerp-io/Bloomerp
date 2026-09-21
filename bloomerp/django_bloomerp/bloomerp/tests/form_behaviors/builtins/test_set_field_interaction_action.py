"""Scenarios for the consolidated field-interaction action."""

from bloomerp.form_behaviors.builtins.set_field_interaction import (
    SET_FIELD_INTERACTION,
)
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorResult,
    FieldStateUpdate,
)
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase


class TestSetFieldInteractionAction(BloomerpBehaviorActionTestCase):
    """Verify enabled and disabled states leave visibility and values untouched."""

    action = SET_FIELD_INTERACTION

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Return enabled and disabled outcomes for one declared target."""
        listener = self.get_application_field("first_name")
        target = self.get_application_field("last_name")
        context = BehaviorContext(
            values={"first_name": "Ada", "last_name": "Lovelace"},
            listener_field="first_name",
            target_field="last_name",
        )
        return [
            BehaviorActionScenario(
                name="Enable the target without changing its visibility",
                context=context,
                listener=listener,
                target=target,
                config={"interaction": "enabled"},
                expected_result=BehaviorResult(
                    states=(FieldStateUpdate(field="last_name", disabled=False),)
                ),
            ),
            BehaviorActionScenario(
                name="Disable the target without changing its visibility",
                context=context,
                listener=listener,
                target=target,
                config={"interaction": "disabled"},
                expected_result=BehaviorResult(
                    states=(FieldStateUpdate(field="last_name", disabled=True),)
                ),
            ),
        ]

