"""Scenarios for direct and related-record field copying."""

from unittest.mock import patch

from django.core.exceptions import ValidationError

from bloomerp.form_behaviors.builtins.copy_field_value import (
    COPY_FIELD_VALUE,
    _read_related_value,
)
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorMessage,
    BehaviorResult,
    FieldValueUpdate,
)
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import (
    BehaviorActionScenario,
    BloomerpBehaviorActionTestCase,
    ExpectedBehaviorActionException,
)


class TestCopyFieldValueAction(BloomerpBehaviorActionTestCase):
    """Verify direct copying, related traversal, policies, and authorization."""

    action = COPY_FIELD_VALUE
    create_foreign_models = True

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Describe the two source modes and their write behavior."""
        related_type = self.CustomerTypeModel.objects.get(name="Retail")
        text_listener = self.get_application_field("first_name")
        relation_listener = self.get_application_field("customer_type")
        target = self.get_application_field("last_name")
        return [
            BehaviorActionScenario(
                name="Copy the listener value directly",
                context=BehaviorContext(
                    values={"first_name": "Ada", "last_name": ""},
                    listener_field="first_name",
                    target_field="last_name",
                ),
                config={"source": "listener"},
                listener=text_listener,
                target=target,
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="last_name", value="Ada"),)
                ),
            ),
            BehaviorActionScenario(
                name="Copy a field from the selected related record",
                context=BehaviorContext(
                    values={
                        "customer_type": str(related_type.pk),
                        "last_name": "Draft",
                    },
                    listener_field="customer_type",
                    target_field="last_name",
                ),
                config={"source": "related_field", "related_field": "name"},
                listener=relation_listener,
                target=target,
                expected_result=BehaviorResult(
                    values=(FieldValueUpdate(field="last_name", value="Retail"),)
                ),
            ),
            BehaviorActionScenario(
                name="Keep a populated target under the empty-only policy",
                context=BehaviorContext(
                    values={"first_name": "Ada", "last_name": "Keep"},
                    listener_field="first_name",
                    target_field="last_name",
                ),
                config={"source": "listener", "write_policy": "if_empty"},
                listener=text_listener,
                target=target,
                expected_result=BehaviorResult(),
            ),
            BehaviorActionScenario(
                name="Do not copy an unchanged related value",
                context=BehaviorContext(
                    values={"customer_type": str(related_type.pk), "last_name": "Retail"},
                    listener_field="customer_type",
                    target_field="last_name",
                ),
                config={"source": "related_field", "related_field": "name"},
                listener=relation_listener,
                target=target,
                expected_result=BehaviorResult(),
            ),
            BehaviorActionScenario(
                name="Do not clear the target when no related record is selected",
                context=BehaviorContext(
                    values={"customer_type": None, "last_name": "Keep"},
                    listener_field="customer_type",
                    target_field="last_name",
                ),
                config={"source": "related_field", "related_field": "name"},
                listener=relation_listener,
                target=target,
                expected_result=BehaviorResult(),
            ),
            BehaviorActionScenario(
                name="Reject a direct source whose value contract differs from the target",
                context=BehaviorContext(
                    values={"age": 42, "last_name": ""},
                    listener_field="age",
                    target_field="last_name",
                ),
                config={"source": "listener"},
                listener=self.get_application_field("age"),
                target=target,
                expected_exception=ExpectedBehaviorActionException(ValidationError),
            ),
        ]

    def test_denied_related_field_returns_no_value(self) -> None:
        """Return a non-mutating permission message for an inaccessible source field."""
        related_type = self.CustomerTypeModel.objects.get(name="Retail")
        listener = self.get_application_field("customer_type")
        target = self.get_application_field("last_name")
        context = BehaviorContext(
            values={
                "customer_type": str(related_type.pk),
                "last_name": "Existing",
            },
            listener_field="customer_type",
            target_field="last_name",
        )
        with patch.object(UserPolicyManager, "has_field_permission", return_value=False):
            result = self.action.run(
                context,
                {"source": "related_field", "related_field": "name"},
                listener=listener,
                target=target,
                user=self.normal_user,
            )
        self.assertEqual(
            result,
            BehaviorResult(
                messages=(BehaviorMessage(
                    type="danger",
                    message="Permission denied: you cannot read the selected related value",
                ),)
            ),
        )

    def test_related_mode_offers_only_compatible_fields(self) -> None:
        """Choose related sources with matching value and relation identities."""
        listener = self.get_application_field("customer_type")
        target = self.get_application_field("last_name")
        form_class = self.action.config_form_factory(target, listener)
        form = form_class(initial={"source": "related_field"})
        self.assertIn("name", form.fields["related_field"].queryset.values_list("field", flat=True))
        self.assertEqual(
            form_class.base_fields["source"].initial,
            "related_field",
        )

        unrelated_target = self.get_application_field("country")
        candidates = ApplicationField.get_for_model(self.CustomerModel)
        self.assertFalse(
            self.action.get_target_fields(candidates, listener)
            .filter(pk=unrelated_target.pk)
            .exists()
        )

    def test_inaccessible_related_row_returns_no_value(self) -> None:
        """Resolve selected records from the row-scoped queryset before reading values."""
        related_type = self.CustomerTypeModel.objects.get(name="Retail")
        listener = self.get_application_field("customer_type")
        target = self.get_application_field("last_name")
        context = BehaviorContext(
            values={"customer_type": str(related_type.pk), "last_name": "Keep"},
            listener_field="customer_type",
            target_field="last_name",
        )
        with patch.object(
            UserPolicyManager,
            "get_accessible_queryset",
            return_value=self.CustomerTypeModel.objects.none(),
        ):
            result = self.action.run(
                context,
                {"source": "related_field", "related_field": "name"},
                listener=listener,
                target=target,
                user=self.admin_user,
            )
        self.assertEqual(result.values, ())
        self.assertEqual(result.messages[0].type, "danger")

    def test_related_foreign_key_is_serialized_as_an_identifier(self) -> None:
        """Copy a relation's stored primary key rather than its model instance."""
        country = self.CountryModel.objects.get(name="Belgium")
        result = _read_related_value(
            self.get_application_field("country"),
            self.get_application_field("planet", self.CountryModel),
            country.pk,
            self.admin_user,
        )
        self.assertEqual(result, (True, str(country.planet_id)))

    def test_direct_relation_requires_the_same_related_model(self) -> None:
        """Reject an identically shaped foreign key pointing at a different model."""
        listener = self.get_application_field("country")
        target = self.get_application_field("customer_type")
        context = BehaviorContext(
            values={"country": None, "customer_type": None},
            listener_field="country",
            target_field="customer_type",
        )
        with self.assertRaises(ValidationError):
            self.action.run(
                context,
                {"source": "listener"},
                listener=listener,
                target=target,
                user=self.admin_user,
            )
