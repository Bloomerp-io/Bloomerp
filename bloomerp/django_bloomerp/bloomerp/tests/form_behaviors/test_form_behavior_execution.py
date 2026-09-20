"""Direct service tests for typed, ordered, side-effect-free behavior evaluation."""
from copy import deepcopy
import json
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.form_behaviors.definition import (
    BehaviorAction, BehaviorActionDefinition, BehaviorConfig, BehaviorContext,
    BehaviorResult, FieldValueUpdate, FormBehavior, CleanedConfigData,
)
from bloomerp.form_behaviors.execution import BehaviorExecutor
from bloomerp.form_behaviors.registry import ACTION_REGISTRY
from bloomerp.form_fields.behavior_field import BehaviorField
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget
from bloomerp.form_behaviors.utils import action_config_form, clean_action_config
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels


def undeclared_update(context: BehaviorContext, config: CleanedConfigData) -> BehaviorResult:
    """Simulate an extension attempting to update a field it did not declare."""
    return BehaviorResult(values=(FieldValueUpdate(field="age", value=20),))


class TestFormBehaviorExecution(BaseBloomerpTestCaseWithModels):
    """Test the service directly using real fields, configurations, and action forms."""

    auto_create_customers = False
    create_foreign_models = True

    def setUp(self) -> None:
        """Create a stored record and a distinct draft for isolation assertions."""
        super().setUp()
        self.customer = self.CustomerModel.objects.create(first_name="Original", last_name="Stored", age=18)
        self.values = {"first_name": "Draft", "last_name": "Stored", "age": "18", "date_joined": ""}

    def _owner(self, behaviors: list[FormBehavior]) -> UserObjectLayoutPreference:
        """Store behaviors on a listener with an explicit set of layout fields."""
        return UserObjectLayoutPreference.objects.create(
            user=self.admin_user, name="Execution unit fixture",
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            layout=FieldLayout(rows=[LayoutRow(columns=4, items=[
                LayoutItem(id="first_name", config={"behaviors": BehaviorConfig(behaviors=behaviors).to_storage()}),
                LayoutItem(id="last_name"), LayoutItem(id="age"), LayoutItem(id="date_joined"),
            ])]).model_dump(mode="json"),
        )

    def _evaluate(self, actions: list[BehaviorAction], **kwargs: Any) -> BehaviorResult:
        """Evaluate one behavior against the stored record without an HTTP request."""
        owner = self._owner([FormBehavior(id="example", actions=actions, **kwargs)])
        return BehaviorExecutor(owner, self.admin_user, instance=self.customer).evaluate("first_name", self.values)

    def test_updates_are_typed_and_neither_input_nor_database_is_mutated(self) -> None:
        """An integer suggestion is coerced while the caller's draft and record remain unchanged."""
        before = deepcopy(self.values)
        result = self._evaluate([BehaviorAction(action="set_value", target_field="age", config={"value": "24"})])
        self.assertEqual(result.values[0].value, 24)
        self.assertEqual(self.values, before)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.age, 18)

    def test_later_behavior_conditions_see_earlier_validated_updates(self) -> None:
        """Rules execute in order and subsequent predicates inspect the updated draft."""
        owner = self._owner([
            FormBehavior(id="set-age", actions=[BehaviorAction(action="set_value", target_field="age", config={"value": "24"})]),
            FormBehavior(id="match-age", conditions=[Filter(connector="AND", conditions=[
                FilterCondition(field_path="age", lookup_id="equals", value=24),
            ])], actions=[BehaviorAction(action="copy_value", target_field="last_name")]),
        ])
        result = BehaviorExecutor(owner, self.admin_user, instance=self.customer).evaluate("first_name", self.values)
        self.assertEqual([update.value for update in result.values], [24, "Draft"])

    def test_or_within_groups_and_and_between_groups(self) -> None:
        """A matching OR alternative satisfies its group, but every group must match."""
        groups = [
            Filter(connector="OR", conditions=[
                FilterCondition(field_path="age", lookup_id="equals", value=99),
                FilterCondition(field_path="age", lookup_id="equals", value=18),
            ]),
            Filter(connector="AND", conditions=[FilterCondition(field_path="first_name", lookup_id="equals", value="Draft")]),
        ]
        action = BehaviorAction(action="copy_value", target_field="last_name")
        self.assertEqual(len(self._evaluate([action], conditions=groups).values), 1)
        groups[1].conditions[0].value = "Different"
        self.assertEqual(self._evaluate([action], conditions=groups).values, ())

    def test_empty_groups_follow_filter_boolean_semantics(self) -> None:
        """No groups and empty AND groups match; an empty OR group does not."""
        action = BehaviorAction(action="copy_value", target_field="last_name")
        for groups, expected in [([], 1), ([Filter(connector="AND")], 1), ([Filter(connector="OR")], 0)]:
            with self.subTest(groups=groups):
                self.assertEqual(len(self._evaluate([action], conditions=groups).values), expected)

    def test_invalid_input_and_invalid_output_are_rejected(self) -> None:
        """Field validators reject malformed draft integers and malformed action suggestions."""
        action = BehaviorAction(action="set_value", target_field="age", config={"value": "not-an-integer"})
        with self.assertRaises(ValidationError):
            self._evaluate([action])
        self.values["age"] = "invalid-draft"
        with self.assertRaises(ValidationError):
            self._evaluate([BehaviorAction(action="hide_field", target_field="last_name")])

    def test_incomplete_optional_draft_fields_are_allowed(self) -> None:
        """A blank date does not require the entire model form to be submission-ready."""
        result = self._evaluate([BehaviorAction(action="set_value", target_field="date_joined", config={"value": "2026-09-20"})])
        self.assertEqual(result.values[0].value, "2026-09-20")

    def test_unknown_action_after_valid_action_returns_no_partial_result(self) -> None:
        """A failed batch raises instead of leaking previously proposed updates or saving them."""
        before = deepcopy(self.values)
        with self.assertRaisesMessage(ValidationError, "Unknown action"):
            self._evaluate([
                BehaviorAction(action="copy_value", target_field="last_name"),
                BehaviorAction(action="does-not-exist"),
            ])
        self.assertEqual(self.values, before)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.last_name, "Stored")

    def test_targetless_message_has_a_valid_collection_contract(self) -> None:
        """Messages work without a target, and invalid tones fail form validation."""
        result = self._evaluate([BehaviorAction(action="show_message", config={"type": "info", "message": "Ready"})])
        self.assertEqual(result.messages[0].message, "Ready")
        with self.assertRaises(ValidationError):
            self._evaluate([BehaviorAction(action="show_message", config={"type": "arbitrary", "message": "Ready"})])

    def test_extensions_cannot_update_an_undeclared_target(self) -> None:
        """Even a trusted registered executor must honor its configured target boundary."""
        definition = BehaviorActionDefinition(id="unit-undeclared", label="Invalid", description="Fixture", requires_target_field=True, execute=undeclared_update)
        ACTION_REGISTRY.register(definition.id, definition)
        self.addCleanup(ACTION_REGISTRY.unregister, definition.id)
        with self.assertRaisesMessage(ValidationError, "undeclared"):
            self._evaluate([BehaviorAction(action=definition, target_field="last_name")])

    def test_form_owned_layout_uses_the_same_executor(self) -> None:
        """An authenticated authorized Form layout evaluates the same declarations as a preference."""
        preference = self._owner([FormBehavior(id="copy", actions=[BehaviorAction(action="copy_value", target_field="last_name")])])
        owner = Form.objects.create(name="Configured form", content_type=preference.content_type, layout=preference.layout)
        result = BehaviorExecutor(owner, self.admin_user).evaluate("first_name", self.values)
        self.assertEqual(result.values[0].value, "Draft")

    def test_other_users_cannot_execute_a_preference_directly(self) -> None:
        """The service enforces ownership even when invoked without the endpoint."""
        owner = self._owner([])
        with self.assertRaises(PermissionDenied):
            BehaviorExecutor(owner, self.normal_user)

    def test_unavailable_or_missing_draft_fields_are_rejected(self) -> None:
        """Unknown fields and omitted listeners cannot bypass the layout boundary."""
        executor = BehaviorExecutor(self._owner([]), self.admin_user)
        with self.assertRaises(PermissionDenied):
            executor.evaluate("first_name", {**self.values, "unknown": "value"})
        with self.assertRaisesMessage(ValidationError, "Listener field"):
            executor.evaluate("first_name", {"age": 18})

    def test_configuration_binding_matches_editor_for_native_json(self) -> None:
        """The editor and executor preserve native JSON strings without double encoding."""
        field = ApplicationField.get_for_model(self.CustomerModel).get(field="first_name")
        definition = ACTION_REGISTRY.get("set_value")
        form = action_config_form(definition, field, field, {"value": "Hello"}, bound=True)
        self.assertTrue(form.is_valid())
        self.assertEqual(clean_action_config(definition, field, field, {"value": "Hello"}), form.cleaned_data)

    def test_collection_values_validate_partial_rows_without_saving_children(self) -> None:
        """A collection may contain incomplete rows, but its supplied columns are typed."""
        country = self.CountryModel.objects.first()
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user, name="Collection draft",
            content_type=ContentType.objects.get_for_model(self.CountryModel),
            layout=FieldLayout(rows=[LayoutRow(columns=2, items=[
                LayoutItem(id="name", config={"behaviors": BehaviorConfig(behaviors=[FormBehavior(
                    id="populate", actions=[BehaviorAction(action="set_value", target_field="customers", config={
                        "value": [{"first_name": "New", "age": "21"}],
                    })],
                )]).to_storage()}),
                LayoutItem(id="customers", config={"inline_fields": ["first_name", "last_name", "age"]}),
            ])]).model_dump(mode="json"),
        )
        count = self.CustomerModel.objects.count()
        executor = BehaviorExecutor(owner, self.admin_user, instance=country)
        result = executor.evaluate("name", {"name": country.name, "customers": []})
        self.assertEqual(result.values[0].value, [{"first_name": "New", "age": 21}])
        self.assertEqual(self.CustomerModel.objects.count(), count)
        with self.assertRaisesMessage(ValidationError, "does not belong"):
            executor.evaluate("name", {"name": country.name, "customers": [{"id": str(self.customer.pk)}]})
        with self.assertRaisesMessage(ValidationError, "columns"):
            executor.evaluate("name", {"name": country.name, "customers": [{"unknown": "value"}]})

    def test_object_values_cannot_be_coerced_to_arbitrary_text(self) -> None:
        """Text targets reject structured values rather than saving Python repr strings."""
        with self.assertRaisesMessage(ValidationError, "scalar"):
            self._evaluate([BehaviorAction(action="set_value", target_field="last_name", config={"value": {"unexpected": True}})])

    def test_collection_condition_capabilities_match_editor_saving_and_execution(self) -> None:
        """O2M count operators are offered, saved, and evaluated against active draft rows."""
        country = self.CountryModel.objects.first()
        fields = ApplicationField.get_for_model(self.CountryModel)
        listener = fields.get(field="name")
        widget = BehaviorBuilderWidget(
            source_field={"id": str(listener.pk)},
            field_catalog=list(fields.filter(field__in=["name", "customers"]).values("id", "field")),
        )
        catalog = json.loads(widget.get_context("behaviors", None, {})["widget"]["conditions_json"])
        collection = next(field for field in catalog if field["field"] == "customers")
        lookup_ids = {lookup["id"] for lookup in collection["lookups"]}
        self.assertIn("count_equals", lookup_ids)
        self.assertNotIn("one_to_many_advanced", lookup_ids)
        cases = [
            ("count_equals", 1, True),
            ("count_greater_than", 1, False),
            ("count_greater_than_or_equal", 1, True),
            ("count_less_than", 2, True),
            ("count_less_than_or_equal", 0, False),
            ("count_equals", 0, False),
        ]
        for lookup_id, value, matches in cases:
            with self.subTest(lookup=lookup_id, value=value):
                config = BehaviorConfig(behaviors=[FormBehavior(
                    id="count-draft", conditions=[Filter(connector="AND", conditions=[
                        FilterCondition(field_path="customers", lookup_id=lookup_id, value=value),
                    ])], actions=[BehaviorAction(action="show_message", config={"type": "info", "message": "Matched"})],
                )]).to_storage()
                self.assertEqual(BehaviorField(widget=widget).clean(config), config)
                owner = UserObjectLayoutPreference.objects.create(
                    user=self.admin_user, name=f"Count {lookup_id} {value}",
                    content_type=ContentType.objects.get_for_model(self.CountryModel),
                    layout=FieldLayout(rows=[LayoutRow(columns=2, items=[
                        LayoutItem(id="name", config={"behaviors": config}),
                        LayoutItem(id="customers", config={"inline_fields": ["first_name"]}),
                    ])]).model_dump(mode="json"),
                )
                executor = BehaviorExecutor(owner, self.admin_user, instance=country)
                result = executor.evaluate("name", {
                    "name": country.name,
                    "customers": [{"first_name": "Active"}, {"first_name": "Removed", "DELETE": True}],
                })
                self.assertEqual(bool(result.messages), matches)
                if lookup_id == "count_equals" and value == 0:
                    empty_result = executor.evaluate("name", {
                        "name": country.name, "customers": [{"DELETE": True}],
                    })
                    self.assertEqual(len(empty_result.messages), 1)

    def test_foreign_key_condition_compares_the_selected_draft_identity(self) -> None:
        """A registered equals evaluator accepts an FK without traversing saved related records."""
        country = self.CountryModel.objects.first()
        planet = self.PlanetModel.objects.create(name="Draft selection")
        fields = ApplicationField.get_for_model(self.CountryModel)
        listener = fields.get(field="name")
        widget = BehaviorBuilderWidget(
            source_field={"id": str(listener.pk)},
            field_catalog=list(fields.filter(field__in=["name", "planet"]).values("id", "field")),
        )
        catalog = json.loads(widget.get_context("behaviors", None, {})["widget"]["conditions_json"])
        relation = next(field for field in catalog if field["field"] == "planet")
        self.assertIn("equals", {lookup["id"] for lookup in relation["lookups"]})
        config = BehaviorConfig(behaviors=[FormBehavior(
            id="selected-planet", conditions=[Filter(connector="AND", conditions=[
                FilterCondition(field_path="planet", lookup_id="equals", value=planet.pk),
            ])], actions=[BehaviorAction(action="show_message", config={"type": "info", "message": "Selected"})],
        )]).to_storage()
        self.assertEqual(BehaviorField(widget=widget).clean(config), config)
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user, name="FK condition",
            content_type=ContentType.objects.get_for_model(self.CountryModel),
            layout=FieldLayout(rows=[LayoutRow(columns=2, items=[
                LayoutItem(id="name", config={"behaviors": config}), LayoutItem(id="planet"),
            ])]).model_dump(mode="json"),
        )
        executor = BehaviorExecutor(owner, self.admin_user, instance=country)
        result = executor.evaluate("name", {"name": country.name, "planet": str(planet.pk)})
        self.assertEqual(len(result.messages), 1)
        result = executor.evaluate("name", {"name": country.name, "planet": None})
        self.assertEqual(result.messages, ())

    def test_non_evaluable_lookup_cannot_be_saved_or_executed(self) -> None:
        """Hidden traversal operators cannot bypass capability checks through submitted JSON."""
        field = ApplicationField.get_for_model(self.CustomerModel).get(field="first_name")
        widget = BehaviorBuilderWidget(source_field={"id": str(field.pk)}, field_catalog=[{"id": field.pk}])
        config = BehaviorConfig(behaviors=[FormBehavior(
            id="unsupported", conditions=[Filter(connector="AND", conditions=[
                FilterCondition(field_path="first_name", lookup_id="foreign_advanced", value=True),
            ])], actions=[BehaviorAction(action="hide_field", target_field="first_name")],
        )])
        with self.assertRaises(ValidationError):
            BehaviorField(widget=widget).clean(config.to_storage())
        with self.assertRaises(ValidationError):
            BehaviorExecutor(self._owner(config.behaviors), self.admin_user).evaluate("first_name", self.values)
