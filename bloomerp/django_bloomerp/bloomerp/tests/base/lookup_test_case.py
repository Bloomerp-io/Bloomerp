from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.db import models

from bloomerp.lookups.definition import (
    BoundLookup,
    CompiledLookup,
    CompiledSQL,
    Lookup,
    LookupDefinition,
    SQLLookupContext,
)
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels


_UNSET = object()


@dataclass(frozen=True)
class PythonEvaluation:
    """One in-memory comparison against a scenario's lookup value."""

    actual: Any
    expected: bool


@dataclass
class LookupScenario:
    """One canonical lookup value exercised across its supported backends."""

    name: str
    application_field: ApplicationField | Callable[[], ApplicationField]
    field_path: str
    expression: str
    value: Any
    expected_lookup: CompiledLookup
    description: str | None = None
    preparation: Callable[[], None] | None = None
    expected_sql: CompiledSQL | None = None
    sql_context: SQLLookupContext | None = None
    sql_value: Any = _UNSET
    python_evaluations: list[PythonEvaluation] = field(default_factory=list)


class BloomerpLookupTestCase(BaseBloomerpTestCaseWithModels):
    """Lookup tests backed by Bloomerp's dynamic models and application fields."""

    lookup: Lookup | None = None

    def get_application_field(
        self,
        field_name: str,
        model: type[models.Model] | None = None,
    ) -> ApplicationField:
        """Resolve a generated application field for a lookup scenario."""

        application_field = ApplicationField.get_by_field(
            model or self.CustomerModel,
            field_name,
        )
        if application_field is None:
            raise AssertionError(
                f"No ApplicationField was generated for {field_name!r}"
            )
        return application_field

    def get_lookup(self) -> BoundLookup:
        if self.lookup is None:
            raise AssertionError("Lookup test cases must define lookup")
        return BoundLookup.normalize(self.lookup)

    def get_test_scenarios(self) -> list[LookupScenario]:
        """Return declarative scenarios for the concrete lookup test case."""

        return []

    def test_lookup_is_valid(self) -> None:
        """Confirm the configured lookup has a valid definition."""

        if self.lookup is None:
            return

        bound_lookup = self.get_lookup()
        self.assertIsInstance(bound_lookup.lookup, LookupDefinition)
        self.assertTrue(bound_lookup.id)

    def test_lookup_scenarios(self) -> None:
        """Run every scenario against each configured lookup backend."""

        if self.lookup is None:
            return

        bound_lookup = self.get_lookup()
        for scenario in self.get_test_scenarios():
            with self.subTest(name=scenario.name):
                self._run_lookup_scenario(bound_lookup, scenario)

    def _run_lookup_scenario(
        self,
        lookup: BoundLookup,
        scenario: LookupScenario,
    ) -> None:
        if scenario.preparation:
            scenario.preparation()

        if not lookup.nested:
            self.assertIn(scenario.expression, lookup.expressions)

        application_field = (
            scenario.application_field()
            if callable(scenario.application_field)
            else scenario.application_field
        )
        self.assertIsInstance(application_field, ApplicationField)

        compiled_lookup = lookup.get_q_factory()(
            application_field,
            scenario.field_path,
            scenario.expression,
            scenario.value,
        )
        self.assertEqual(compiled_lookup, scenario.expected_lookup)

        if scenario.expected_sql is not None:
            sql_factory = lookup.get_sql_factory()
            if sql_factory is None:
                self.fail(
                    f"Lookup {lookup.id!r} has an SQL expectation but no SQL factory"
                )
            sql_context = scenario.sql_context or SQLLookupContext(
                field_path=scenario.field_path
            )
            sql_value = (
                scenario.value if scenario.sql_value is _UNSET else scenario.sql_value
            )
            compiled_sql = sql_factory(
                sql_context,
                scenario.expression,
                sql_value,
            )
            self.assertEqual(compiled_sql, scenario.expected_sql)

        if scenario.python_evaluations:
            evaluator = lookup.get_python_evaluator()
            if evaluator is None:
                self.fail(
                    f"Lookup {lookup.id!r} has Python evaluations but no evaluator"
                )
            for evaluation in scenario.python_evaluations:
                with self.subTest(actual=evaluation.actual):
                    self.assertIs(
                        evaluator(evaluation.actual, scenario.value),
                        evaluation.expected,
                    )
