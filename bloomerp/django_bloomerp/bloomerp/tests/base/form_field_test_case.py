from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Literal, TypeVar

from django import forms
from django.test import SimpleTestCase


FieldType = TypeVar("FieldType", bound=forms.Field)
_UNSET = object()


@dataclass(frozen=True)
class ExpectedFormFieldException:
    """An exception expected during one standalone form-field operation."""

    phase: Literal["construct", "clean"]
    exception: type[Exception] | tuple[type[Exception], ...]
    message_regex: str | None = None


@dataclass
class FormFieldScenario(Generic[FieldType]):
    """Declarative construction and cleaning expectations for a form field.

    Each scenario constructs a fresh field. Set ``clean_value`` to enable the
    field's ``clean`` phase; the private sentinel makes explicit ``None``
    inputs distinguishable from a scenario with no clean operation.
    """

    name: str
    description: str | None = None
    preparation: Callable[[], None] | None = None
    constructor_args: tuple[Any, ...] | Callable[[], tuple[Any, ...]] = ()
    constructor_kwargs: dict[str, Any] | Callable[[], dict[str, Any]] = field(
        default_factory=dict
    )
    post_construction: Callable[[FieldType], None] | None = None
    constructor_validators: Callable[[FieldType], bool] | list[
        Callable[[FieldType], bool]
    ] = field(default_factory=list)
    clean_value: Any = _UNSET
    clean_result_validators: Callable[[Any], bool] | list[Callable[[Any], bool]] = (
        field(default_factory=list)
    )
    expected_exceptions: list[ExpectedFormFieldException] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        """Reject expectations for phases that this scenario cannot reach."""
        phases = [expected.phase for expected in self.expected_exceptions]
        if len(phases) != len(set(phases)):
            raise ValueError("expected_exceptions may contain only one entry per phase")

        phase_configuration = {
            "construct": True,
            "clean": self.clean_value is not _UNSET,
        }
        phase_validators = {
            "construct": self.constructor_validators,
            "clean": self.clean_result_validators,
        }
        for phase, is_configured in phase_configuration.items():
            if phase_validators[phase] and not is_configured:
                raise ValueError(f"{phase} validators require that phase to be configured")

        for expected in self.expected_exceptions:
            if not phase_configuration[expected.phase]:
                raise ValueError(
                    f"Expected {expected.phase} exceptions require that phase to be configured"
                )
            if phase_validators[expected.phase]:
                raise ValueError(
                    f"{expected.phase} validators cannot be configured when that phase "
                    "is expected to fail"
                )


class BloomerpFormFieldTestCase(SimpleTestCase, Generic[FieldType]):
    """Base class providing database-free checks for standalone form fields."""

    field_class: type[FieldType] | None = None

    def get_field_args(self) -> tuple[Any, ...]:
        """Return positional constructor arguments for fields needing setup."""
        return ()

    def get_field_kwargs(self) -> dict[str, Any]:
        """Return keyword constructor arguments for fields needing setup."""
        return {}

    def test_form_field_is_valid(self) -> None:
        """Confirm the configured field and its widget can be constructed."""
        if self.field_class is None:
            return

        self.assertTrue(issubclass(self.field_class, forms.Field))
        field_instance = self.field_class(
            *self.get_field_args(), **self.get_field_kwargs()
        )
        self._validate_field(field_instance)

    def get_test_scenarios(self) -> list[FormFieldScenario[FieldType]]:
        """Return declarative scenarios for the concrete form-field test case."""
        return []

    def test_form_field_scenarios(self) -> None:
        """Run every declared scenario with a fresh field instance."""
        if self.field_class is None:
            return

        for scenario in self.get_test_scenarios():
            with self.subTest(name=scenario.name):
                self._run_form_field_scenario(scenario)

    def _run_form_field_scenario(
        self, scenario: FormFieldScenario[FieldType]
    ) -> None:
        """Run the ordered operations configured for one scenario."""
        if scenario.preparation:
            scenario.preparation()

        expected_exception = self._expected_exception(scenario, "construct")
        if expected_exception:
            self._assert_expected_form_field_exception(
                expected_exception,
                lambda: self._construct_field(
                    scenario.constructor_args, scenario.constructor_kwargs
                ),
            )
            return

        field_instance = self._construct_field(
            scenario.constructor_args, scenario.constructor_kwargs
        )
        self._validate_field(field_instance)
        if scenario.post_construction:
            scenario.post_construction(field_instance)
        self._run_validators(
            scenario.constructor_validators,
            field_instance,
            phase="construct",
            scenario=scenario,
        )

        if scenario.clean_value is _UNSET:
            return

        expected_exception = self._expected_exception(scenario, "clean")
        if expected_exception:
            self._assert_expected_form_field_exception(
                expected_exception,
                lambda: field_instance.clean(scenario.clean_value),
            )
            return

        result = field_instance.clean(scenario.clean_value)
        self._run_validators(
            scenario.clean_result_validators,
            result,
            phase="clean",
            scenario=scenario,
        )

    def _construct_field(
        self,
        constructor_args: tuple[Any, ...] | Callable[[], tuple[Any, ...]],
        constructor_kwargs: dict[str, Any] | Callable[[], dict[str, Any]],
    ) -> FieldType:
        """Construct the configured field from eager arguments or factories."""
        if self.field_class is None:
            raise AssertionError("Form field test cases must define field_class")

        args = constructor_args() if callable(constructor_args) else constructor_args
        kwargs = (
            constructor_kwargs()
            if callable(constructor_kwargs)
            else constructor_kwargs
        )
        return self.field_class(*args, **kwargs)

    @staticmethod
    def _expected_exception(
        scenario: FormFieldScenario[FieldType],
        phase: Literal["construct", "clean"],
    ) -> ExpectedFormFieldException | None:
        """Return the exception expectation for one form-field phase, if any."""
        return next(
            (
                expected
                for expected in scenario.expected_exceptions
                if expected.phase == phase
            ),
            None,
        )

    def _assert_expected_form_field_exception(
        self,
        expected: ExpectedFormFieldException,
        operation: Callable[[], Any],
    ) -> None:
        """Assert one expected exception without transaction handling."""
        if expected.message_regex is None:
            assertion = self.assertRaises(expected.exception)
        else:
            assertion = self.assertRaisesRegex(
                expected.exception,
                expected.message_regex,
            )

        with assertion:
            operation()

    def _run_validators(
        self,
        validators: Callable[[Any], bool] | list[Callable[[Any], bool]],
        value: Any,
        *,
        phase: str,
        scenario: FormFieldScenario[FieldType],
    ) -> None:
        """Assert every validator configured for one successful phase."""
        if callable(validators):
            validators = [validators]

        for validator in validators:
            validator_name = getattr(validator, "__name__", type(validator).__name__)
            description = f": {scenario.description}" if scenario.description else ""
            self.assertTrue(
                validator(value),
                f"{phase.capitalize()} validator {validator_name!r} failed for "
                f"scenario {scenario.name!r}{description}",
            )

    def _validate_field(self, field_instance: FieldType) -> None:
        """Confirm the field and its assigned widget are Django form objects."""
        self.assertIsInstance(field_instance, forms.Field)
        self.assertIsInstance(field_instance.widget, forms.Widget)
