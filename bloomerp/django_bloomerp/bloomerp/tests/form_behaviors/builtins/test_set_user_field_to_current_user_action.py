"""Tests for assigning the behavior evaluator to a user field."""

from django.contrib.auth.models import AnonymousUser

from bloomerp.form_behaviors.builtins.set_user_field_to_current_user import (
    SET_USER_FIELD_TO_CURRENT_USER,
)
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorMessage,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase


class TestSetUserFieldToCurrentUserAction(BloomerpBehaviorActionTestCase):
    """Verify assignment, no-op behavior, eligibility, and anonymous denial."""

    action = SET_USER_FIELD_TO_CURRENT_USER

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Assign the current user and avoid an update when already selected."""
        listener = self.get_application_field("first_name")
        target = self.get_application_field("user_account")
        return [
            BehaviorActionScenario(
                name="The authenticated evaluator is assigned to the target",
                context=BehaviorContext(
                    values={"first_name": "Draft", "user_account": None},
                    listener_field="first_name",
                    target_field="user_account",
                ),
                listener=listener,
                target=target,
                expected_result=BehaviorResult(
                    values=(
                        FieldValueUpdate(
                            field="user_account",
                            value=self.admin_user.pk,
                        ),
                    )
                ),
            ),
            BehaviorActionScenario(
                name="An already selected current user produces no update",
                context=BehaviorContext(
                    values={"first_name": "Draft", "user_account": self.admin_user.pk},
                    listener_field="first_name",
                    target_field="user_account",
                ),
                listener=listener,
                target=target,
                expected_result=BehaviorResult(),
            ),
        ]

    def test_only_user_fields_are_eligible_targets(self) -> None:
        """Exclude ordinary relation and scalar fields from target selection."""
        fields = self.action.get_target_fields(
            ApplicationField.get_for_model(self.CustomerModel),
            self.get_application_field("first_name"),
        )
        eligible = set(fields.values_list("field", flat=True))
        self.assertIn("user_account", eligible)
        self.assertNotIn("first_name", eligible)

    def test_anonymous_user_returns_permission_denied_result(self) -> None:
        """Use the shared permission result when no authenticated identity exists."""
        result = self.action.execute(
            BehaviorContext(
                values={"user_account": None},
                listener_field="first_name",
                target_field="user_account",
            ),
            {},
            AnonymousUser(),
        )
        self.assertEqual(
            result,
            BehaviorResult(
                messages=(
                    BehaviorMessage(
                        type="danger",
                        message="Permission denied: an authenticated user is required",
                    ),
                )
            ),
        )

    def test_definition_has_clear_copy_and_group(self) -> None:
        """Expose understandable editor metadata."""
        self.assertEqual(self.action.group, "Field values")
        self.assertIn("authenticated user", self.action.description.lower())
