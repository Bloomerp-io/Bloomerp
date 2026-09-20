"""Scenario-based checks for individual form behavior action definitions."""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from django.db import models

from bloomerp.form_behaviors.definition import (
    BehaviorActionDefinition,
    BehaviorContext,
    BehaviorResult,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels


@dataclass(frozen=True)
class ExpectedBehaviorActionException:
    """An error expected from configuration validation or action execution."""

    exception: type[Exception] | tuple[type[Exception], ...]
    message_regex: str | None = None


@dataclass
class BehaviorActionScenario:
    """Inputs and an exact result or exception for one action invocation."""

    name: str
    context: BehaviorContext | Callable[[], BehaviorContext]
    description: str | None = None
    preparation: Callable[[], None] | None = None
    config: Mapping[str, Any] | Callable[[], Mapping[str, Any]] = field(default_factory=dict)
    listener: ApplicationField | Callable[[], ApplicationField] | None = None
    target: ApplicationField | Callable[[], ApplicationField] | None = None
    expected_result: BehaviorResult | None = None
    expected_exception: ExpectedBehaviorActionException | None = None

    def __post_init__(self) -> None:
        """Require an explicit outcome, including for actions returning no updates."""
        if (self.expected_result is None) == (self.expected_exception is None):
            raise ValueError("Supply exactly one expected_result or expected_exception.")


class BloomerpBehaviorActionTestCase(BaseBloomerpTestCaseWithModels):
    """Test an action's public run contract using dynamic-model fixtures."""

    action: BehaviorActionDefinition | None = None

    def get_application_field(
        self, field_name: str, model: type[models.Model] | None = None,
    ) -> ApplicationField:
        """Resolve an application field on the customer fixture or a supplied model."""
        application_field = ApplicationField.get_by_field(model or self.CustomerModel, field_name)
        if application_field is None:
            raise AssertionError(f"No ApplicationField was generated for {field_name!r}")
        return application_field

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Return the concrete action's descriptive execution scenarios."""
        return []

    def test_behavior_action_is_valid(self) -> None:
        """Check the configured definition without requiring action-specific fixtures."""
        if self.action is None:
            return
        self.assertIsInstance(self.action, BehaviorActionDefinition)
        self.assertTrue(self.action.id)
        self.assertTrue(self.action.label)
        self.assertIsInstance(self.action.requires_target_field, bool)
        for callback in (
            self.action.execute, self.action.config_form_factory,
            self.action.get_listener_fields, self.action.get_target_fields,
        ):
            self.assertTrue(callable(callback))

    def test_behavior_action_scenarios(self) -> None:
        """Validate configuration and execute each scenario under a named subtest."""
        if self.action is None:
            return
        for scenario in self.get_test_scenarios():
            with self.subTest(name=scenario.name, description=scenario.description):
                self._run_behavior_action_scenario(scenario)

    def _run_behavior_action_scenario(self, scenario: BehaviorActionScenario) -> None:
        """Resolve prepared fixtures and verify the action result and draft immutability."""
        if self.action is None:
            raise AssertionError("Behavior action test cases must define action")
        if scenario.preparation:
            scenario.preparation()
        context = scenario.context() if callable(scenario.context) else scenario.context
        config = scenario.config() if callable(scenario.config) else scenario.config
        listener = scenario.listener() if callable(scenario.listener) else scenario.listener
        target = scenario.target() if callable(scenario.target) else scenario.target
        original_values = deepcopy(context.values)
        try:
            expected = scenario.expected_exception
            if expected is not None:
                assertion = (
                    self.assertRaises(expected.exception)
                    if expected.message_regex is None
                    else self.assertRaisesRegex(expected.exception, expected.message_regex)
                )
                with assertion:
                    self.action.run(context, config, listener=listener, target=target)
            else:
                result = self.action.run(context, config, listener=listener, target=target)
                self.assertIsInstance(result, BehaviorResult)
                self.assertEqual(result, scenario.expected_result)
        finally:
            self.assertEqual(context.values, original_values, "Actions must not mutate draft values")
