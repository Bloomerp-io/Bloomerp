"""Direct service tests for typed, ordered, side-effect-free behavior evaluation."""
import json
from copy import deepcopy
from typing import Any, cast
from unittest.mock import patch

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest
from django.test import RequestFactory

from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorActionDefinition,
    BehaviorConfig,
    BehaviorContext,
    BehaviorResult,
    BehaviorUser,
    CleanedConfigData,
    FieldStateUpdate,
    FieldValueUpdate,
    FormBehavior,
)
from bloomerp.form_behaviors.execution import BehaviorExecutor
from bloomerp.form_behaviors.registry import ACTION_REGISTRY
from bloomerp.form_behaviors.utils import action_config_form, clean_action_config
from bloomerp.form_fields.behavior_field import BehaviorField
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.forms.form import Form
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget


def undeclared_update(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Simulate an extension attempting to update a field it did not declare."""
    return BehaviorResult(values=(FieldValueUpdate(field="age", value=20),))


def listener_update(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Simulate a targetless action that safely replaces its triggering value."""
    return BehaviorResult(
        values=(FieldValueUpdate(field=context.listener_field, value="Updated"),)
    )


def disabled_state_update(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return an explicitly disabled state for executor contract coverage."""
    return BehaviorResult(states=(FieldStateUpdate(
        field=context.target_field, visible=True, disabled=True,
    ),))


def invalid_disabled_state_update(
    context: BehaviorContext,
    config: CleanedConfigData,
    user: BehaviorUser,
) -> BehaviorResult:
    """Return a non-boolean disabled value from an extension fixture."""
    return BehaviorResult(states=(FieldStateUpdate(
        field=context.target_field,
        visible=True,
        disabled=cast(Any, "yes"),
    ),))


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
            ])], actions=[BehaviorAction(
                action="copy_field_value",
                target_field="last_name",
                config={"source": "listener"},
            )]),
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
        action = BehaviorAction(
            action="copy_field_value",
            target_field="last_name",
            config={"source": "listener"},
        )
        self.assertEqual(len(self._evaluate([action], conditions=groups).values), 1)
        groups[1].conditions[0].value = "Different"
        self.assertEqual(self._evaluate([action], conditions=groups).values, ())

    def test_empty_groups_follow_filter_boolean_semantics(self) -> None:
        """No groups and empty AND groups match; an empty OR group does not."""
        action = BehaviorAction(
            action="copy_field_value",
            target_field="last_name",
            config={"source": "listener"},
        )
        for groups, expected in [([], 1), ([Filter(connector="AND")], 1), ([Filter(connector="OR")], 0)]:
            with self.subTest(groups=groups):
                self.assertEqual(len(self._evaluate([action], conditions=groups).values), expected)

    def test_invalid_input_and_invalid_output_are_rejected(self) -> None:
        """Field validators reject malformed required drafts and action suggestions."""
        action = BehaviorAction(action="set_value", target_field="age", config={"value": "not-an-integer"})
        with self.assertRaises(ValidationError):
            self._evaluate([action])
        self.values["age"] = "invalid-draft"
        with self.assertRaises(ValidationError):
            self._evaluate([BehaviorAction(
                action="set_field_visibility",
                target_field="age",
                config={"visibility": "hidden"},
            )])

    def test_incomplete_optional_draft_fields_are_allowed(self) -> None:
        """A blank date does not require the entire model form to be submission-ready."""
        result = self._evaluate([BehaviorAction(action="set_value", target_field="date_joined", config={"value": "2026-09-20"})])
        self.assertEqual(result.values[0].value, "2026-09-20")

    def test_unknown_action_after_valid_action_returns_no_partial_result(self) -> None:
        """A failed batch raises instead of leaking previously proposed updates or saving them."""
        before = deepcopy(self.values)
        with self.assertRaisesMessage(ValidationError, "Unknown action"):
            self._evaluate([
                BehaviorAction(
                    action="copy_field_value",
                    target_field="last_name",
                    config={"source": "listener"},
                ),
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

    def test_unrelated_read_only_property_is_not_cleaned(self) -> None:
        """Rendered properties outside the selected behavior do not block execution."""
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        property_field = ApplicationField.objects.create(
            content_type=content_type,
            field="display_total",
            field_type=FIELD_TYPE_REGISTRY.PROPERTY.id,
        )
        owner = self._owner(
            [
                FormBehavior(
                    id="message",
                    actions=[
                        BehaviorAction(
                            action="show_message",
                            config={"type": "info", "message": "Ready"},
                        )
                    ],
                )
            ]
        )
        layout = owner.layout_obj.model_copy(deep=True)
        layout.rows[0].items.append(LayoutItem(id=property_field.field))
        owner.layout = layout.model_dump(mode="json")
        owner.save(update_fields=["layout"])

        result = BehaviorExecutor(
            owner, self.admin_user, instance=self.customer
        ).evaluate(
            "first_name",
            {**self.values, property_field.field: "Read-only total"},
        )

        self.assertEqual(result.messages[0].message, "Ready")

    def test_executor_passes_request_and_user_to_action_callbacks(self) -> None:
        """Action factories and executors receive their scoped HTTP/auth context."""
        observed: dict[str, object] = {}

        def config_form_factory(
            target: ApplicationField | None,
            listener: ApplicationField | None,
            request: HttpRequest | None = None,
        ) -> type[forms.Form]:
            """Record the request supplied while validating action configuration."""
            observed["request"] = request
            return forms.Form

        def execute_with_user(
            context: BehaviorContext,
            config: CleanedConfigData,
            user: BehaviorUser,
        ) -> BehaviorResult:
            """Record the user supplied while executing the configured action."""
            observed["user"] = user
            return BehaviorResult()

        definition = BehaviorActionDefinition(
            id="unit-context-aware",
            label="Context-aware action",
            description="Fixture",
            requires_target_field=False,
            execute=execute_with_user,
            config_form_factory=config_form_factory,
        )
        ACTION_REGISTRY.register(definition.id, definition)
        self.addCleanup(ACTION_REGISTRY.unregister, definition.id)
        owner = self._owner(
            [
                FormBehavior(
                    id="context-aware",
                    actions=[BehaviorAction(action=definition)],
                )
            ]
        )
        request = RequestFactory().post("/components/form_behavior/execute/")
        request.user = self.admin_user

        BehaviorExecutor(
            owner,
            self.admin_user,
            instance=self.customer,
            request=request,
        ).evaluate("first_name", self.values)

        self.assertIs(observed["request"], request)
        self.assertIs(observed["user"], self.admin_user)

    def test_extensions_cannot_update_an_undeclared_target(self) -> None:
        """Even a trusted registered executor must honor its configured target boundary."""
        definition = BehaviorActionDefinition(id="unit-undeclared", label="Invalid", description="Fixture", requires_target_field=True, execute=undeclared_update)
        ACTION_REGISTRY.register(definition.id, definition)
        self.addCleanup(ACTION_REGISTRY.unregister, definition.id)
        with self.assertRaisesMessage(ValidationError, "undeclared"):
            self._evaluate([BehaviorAction(action=definition, target_field="last_name")])

    def test_targetless_actions_may_update_their_layout_listener(self) -> None:
        """Targetless actions retain a safe, useful self-update capability."""
        definition = BehaviorActionDefinition(
            id="unit-listener-update",
            label="Listener update",
            description="Fixture",
            requires_target_field=False,
            execute=listener_update,
        )
        ACTION_REGISTRY.register(definition.id, definition)
        self.addCleanup(ACTION_REGISTRY.unregister, definition.id)
        result = self._evaluate([BehaviorAction(action=definition)])
        self.assertEqual(result.values, (FieldValueUpdate(
            field="first_name", value="Updated",
        ),))

    def test_state_updates_keep_unspecified_state_and_validate_explicit_values(self) -> None:
        """Visibility leaves interaction unchanged and explicit disabled must be boolean."""
        hidden = self._evaluate([
            BehaviorAction(
                action="set_field_visibility",
                target_field="last_name",
                config={"visibility": "hidden"},
            )
        ])
        self.assertEqual(hidden.states, (FieldStateUpdate(
            field="last_name", visible=False, disabled=None,
        ),))
        for definition, expected in (
            (BehaviorActionDefinition(
                id="unit-disabled-state",
                label="Disabled state",
                description="Fixture",
                requires_target_field=True,
                execute=disabled_state_update,
            ), True),
            (BehaviorActionDefinition(
                id="unit-invalid-disabled-state",
                label="Invalid disabled state",
                description="Fixture",
                requires_target_field=True,
                execute=invalid_disabled_state_update,
            ), False),
        ):
            with self.subTest(action=definition.id):
                ACTION_REGISTRY.register(definition.id, definition)
                self.addCleanup(ACTION_REGISTRY.unregister, definition.id)
                action = BehaviorAction(action=definition, target_field="last_name")
                if expected:
                    result = self._evaluate([action])
                    self.assertTrue(result.states[0].disabled)
                else:
                    with self.assertRaisesMessage(ValidationError, "invalid state"):
                        self._evaluate([action])

    def test_interaction_states_preserve_values_and_storage(self) -> None:
        """Interaction-only actions target one authorized field without value writes."""
        for interaction, disabled in (
            ("disabled", True),
            ("enabled", False),
        ):
            with self.subTest(interaction=interaction):
                before = deepcopy(self.values)
                result = self._evaluate([BehaviorAction(
                    action="set_field_interaction",
                    target_field="last_name",
                    config={"interaction": interaction},
                )])
                self.assertEqual(result.values, ())
                self.assertEqual(result.states, (FieldStateUpdate(
                    field="last_name",
                    visible=None,
                    disabled=disabled,
                ),))
                self.assertEqual(self.values, before)
                self.customer.refresh_from_db()
                self.assertEqual(self.customer.last_name, "Stored")

    def test_field_interaction_requires_a_declared_layout_target(self) -> None:
        """Interaction state cannot escape the executor's layout target boundary."""
        owner = self._owner([FormBehavior(
            id="disable-last-name",
            actions=[BehaviorAction(
                action="set_field_interaction",
                target_field="last_name",
                config={"interaction": "disabled"},
            )],
        )])
        executor = BehaviorExecutor(owner, self.admin_user, instance=self.customer)
        executor.fields.pop("last_name")
        with self.assertRaises(PermissionDenied):
            executor.evaluate("first_name", self.values)

    def test_form_owned_layout_uses_the_same_executor(self) -> None:
        """An authenticated authorized Form layout evaluates the same declarations as a preference."""
        preference = self._owner([FormBehavior(id="copy", actions=[BehaviorAction(
            action="copy_field_value",
            target_field="last_name",
            config={"source": "listener"},
        )])])
        owner = Form.objects.create(name="Configured form", content_type=preference.content_type, layout=preference.layout)
        result = BehaviorExecutor(owner, self.admin_user).evaluate("first_name", self.values)
        self.assertEqual(result.values[0].value, "Draft")

    def test_other_users_cannot_execute_a_preference_directly(self) -> None:
        """The service enforces ownership even when invoked without the endpoint."""
        owner = self._owner([])
        with self.assertRaises(PermissionDenied):
            BehaviorExecutor(owner, self.normal_user)

    def test_shared_preference_can_execute_directly(self) -> None:
        """The service accepts an effective preference currently shared to the user."""
        owner = self._owner(
            [
                FormBehavior(
                    id="shared-copy",
                    actions=[
                        BehaviorAction(
                            action="copy_field_value",
                            target_field="last_name",
                            config={"source": "listener"},
                        )
                    ],
                )
            ]
        )
        owner.user = self.normal_user
        owner.save(update_fields=["user"])
        owner.shared_with_users.add(self.admin_user)

        result = BehaviorExecutor(owner, self.admin_user).evaluate(
            "first_name",
            self.values,
        )

        self.assertEqual(result.values[0].value, "Draft")

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

    def test_editor_catalog_contains_only_consolidated_actions(self) -> None:
        """Offer the three merged actions without exposing removed action IDs."""
        listener = ApplicationField.get_for_model(self.CustomerModel).get(field="first_name")
        target = ApplicationField.get_for_model(self.CustomerModel).get(field="last_name")
        widget = BehaviorBuilderWidget(
            source_field={"id": str(listener.pk)},
            field_catalog=[{"id": listener.pk}, {"id": target.pk}],
        )
        actions = json.loads(widget.get_context("behaviors", None, None)["widget"]["actions_json"])
        offered = {action["id"]: action for action in actions}

        self.assertIn("set_field_visibility", offered)
        self.assertIn("set_field_interaction", offered)
        self.assertIn("copy_field_value", offered)
        self.assertEqual(offered["set_field_visibility"]["group"], "Field state")
        self.assertTrue({"show_field", "hide_field", "enable_field", "disable_field", "copy_value", "copy_related_value"}.isdisjoint(offered))

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
            ])], actions=[BehaviorAction(
                action="set_field_visibility",
                target_field="first_name",
                config={"visibility": "hidden"},
            )],
        )])
        with self.assertRaises(ValidationError):
            BehaviorField(widget=widget).clean(config.to_storage())
        with self.assertRaises(ValidationError):
            BehaviorExecutor(self._owner(config.behaviors), self.admin_user).evaluate("first_name", self.values)

    def test_o2m_config_form_rebuilds_compatible_accessor_choices(self) -> None:
        """Partial initial selections expose compatible related fields and reject stale accessors."""
        fields = ApplicationField.get_for_model(self.CountryModel)
        target = fields.get(field="customers")
        listener = fields.get(field="name")
        action = ACTION_REGISTRY.get("set_o2m_value")
        config = {"from_column": "customer_type", "to_column": "first_name", "accessor": "name"}
        form = action_config_form(action, listener, target, config)
        self.assertEqual(form.refresh_fields, ("from_column", "to_column"))
        self.assertTrue(form.fields["accessor"].queryset.filter(field="name").exists())
        cleaned = clean_action_config(action, listener, target, config)
        self.assertEqual(cleaned["accessor"].field, "name")
        changed = {**config, "from_column": "last_name"}
        form = action_config_form(action, listener, target, changed)
        self.assertTrue(form.fields["accessor"].widget.is_hidden)
        self.assertIsNone(form.initial["accessor"])
        self.assertEqual(changed["accessor"], "name")
        with self.assertRaises(ValidationError):
            clean_action_config(action, listener, target, changed)
        with self.assertRaises(ValidationError):
            clean_action_config(action, listener, target, {**config, "to_column": "age"})

    def test_o2m_accessor_copies_authorized_values_without_writing_records(self) -> None:
        """Each active row receives the related field; empty/deleted rows and stored records stay unchanged."""
        country = self.CountryModel.objects.first()
        source_record = self.CustomerTypeModel.objects.first()
        owner = UserObjectLayoutPreference.objects.create(
            user=self.admin_user, name="Copy related value",
            content_type=ContentType.objects.get_for_model(self.CountryModel),
            layout=FieldLayout(rows=[LayoutRow(columns=2, items=[
                LayoutItem(id="name", config={"behaviors": BehaviorConfig(behaviors=[FormBehavior(
                    id="copy-related", actions=[BehaviorAction(
                        action="set_o2m_value", target_field="customers",
                        config={"from_column": "customer_type", "accessor": "name", "to_column": "first_name"},
                    )],
                )]).to_storage()}),
                LayoutItem(id="customers", config={"inline_fields": ["first_name", "customer_type"]}),
            ])]).model_dump(mode="json"),
        )
        values = {"name": country.name, "customers": [
            {"customer_type": str(source_record.pk), "first_name": "Before"},
            {"customer_type": None, "first_name": "Keep empty source"},
            {"customer_type": str(source_record.pk), "first_name": "Keep deleted", "DELETE": True},
        ]}
        original = deepcopy(values)
        count = self.CustomerModel.objects.count()
        executor = BehaviorExecutor(owner, self.admin_user, instance=country)
        result = executor.evaluate("name", values)
        self.assertEqual([row["first_name"] for row in result.values[0].value], [
            source_record.name, "Keep empty source", "Keep deleted",
        ])
        self.assertEqual(values, original)
        self.assertEqual(self.CustomerModel.objects.count(), count)
        with patch(
            "bloomerp.form_behaviors.builtins.set_o2m_value."
            "UserPolicyManager.get_accessible_fields_for_object",
            return_value=ApplicationField.objects.none(),
        ):
            denied = executor.evaluate("name", values)
        self.assertEqual(denied.values, ())
        self.assertIn("Permission denied", denied.messages[0].message)
