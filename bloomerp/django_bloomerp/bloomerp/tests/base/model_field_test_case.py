from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Literal, TypeVar

from django.db import models
from django.test import SimpleTestCase


FieldType = TypeVar("FieldType", bound=models.Field)
_UNSET = object()


@dataclass(frozen=True)
class ExpectedModelFieldException:
    """An exception expected during one model-field operation."""

    phase: Literal[
        "construct", "deconstruct", "to_python", "get_prep_value", "form_clean"
    ]
    exception: type[Exception] | tuple[type[Exception], ...]
    message_regex: str | None = None


@dataclass
class ModelFieldScenario(Generic[FieldType]):
    """Declarative conversion and form-cleaning expectations for a model field.

    Every scenario constructs a fresh field and deconstructs it for Django's
    migration representation. Optional input values independently enable the
    ``to_python``, ``get_prep_value``, and ``formfield().clean`` phases.
    """

    name: str
    description: str | None = None
    preparation: Callable[[], None] | None = None
    post_construction: Callable[[FieldType], None] | None = None
    constructor_kwargs: dict[str, Any] | Callable[[], dict[str, Any]] = field(
        default_factory=dict
    )
    construct_validators: Callable[[FieldType], bool] | list[
        Callable[[FieldType], bool]
    ] = field(default_factory=list)
    deconstruct_validators: Callable[[tuple[str, str, list[Any], dict[str, Any]]], bool] | list[
        Callable[[tuple[str, str, list[Any], dict[str, Any]]], bool]
    ] = field(default_factory=list)
    to_python_value: Any = _UNSET
    to_python_validators: Callable[[Any], bool] | list[Callable[[Any], bool]] = field(
        default_factory=list
    )
    get_prep_value: Any = _UNSET
    get_prep_value_validators: Callable[[Any], bool] | list[
        Callable[[Any], bool]
    ] = field(default_factory=list)
    form_clean_value: Any = _UNSET
    form_clean_validators: Callable[[Any], bool] | list[Callable[[Any], bool]] = field(
        default_factory=list
    )
    expected_exceptions: list[ExpectedModelFieldException] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        """Reject expectations for phases that this scenario cannot reach."""
        phases = [expected.phase for expected in self.expected_exceptions]
        if len(phases) != len(set(phases)):
            raise ValueError("expected_exceptions may contain only one entry per phase")

        phase_configuration = {
            "construct": True,
            "deconstruct": True,
            "to_python": self.to_python_value is not _UNSET,
            "get_prep_value": self.get_prep_value is not _UNSET,
            "form_clean": self.form_clean_value is not _UNSET,
        }
        phase_validators = {
            "construct": self.construct_validators,
            "deconstruct": self.deconstruct_validators,
            "to_python": self.to_python_validators,
            "get_prep_value": self.get_prep_value_validators,
            "form_clean": self.form_clean_validators,
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


class BloomerpModelFieldTestCase(SimpleTestCase, Generic[FieldType]):
    """Base class providing common validity checks for a model field."""

    field_class: type[FieldType] | None = None

    def get_field_kwargs(self) -> dict[str, Any]:
        """Return constructor arguments for fields that need custom setup."""
        return {}

    def test_model_field_is_valid(self) -> None:
        """
        Use case: An app exposes a custom Django model field.
        Expected result: The field can be constructed and deconstructed by Django.
        """
        # 1. Do not execute the reusable base class itself.
        if self.field_class is None:
            return

        # 2. Instantiate and validate Django's migration representation.
        self.assertTrue(issubclass(self.field_class, models.Field))
        field_instance = self.field_class(**self.get_field_kwargs())
        deconstruction = field_instance.deconstruct()

        # 3. Confirm the field exposes a reusable import path and arguments.
        self._validate_deconstruction(deconstruction)

    def get_test_scenarios(self) -> list[ModelFieldScenario[FieldType]]:
        """Return declarative model-field scenarios for the concrete test case."""
        return []

    def test_model_field_scenarios(self) -> None:
        """Run each declared model-field scenario with a fresh field instance."""
        if self.field_class is None:
            return

        for scenario in self.get_test_scenarios():
            with self.subTest(name=scenario.name):
                self._run_model_field_scenario(scenario)

    def _run_model_field_scenario(
        self, scenario: ModelFieldScenario[FieldType]
    ) -> None:
        """Run every operation reached by one model-field scenario."""
        if scenario.preparation:
            scenario.preparation()

        expected_exception = self._expected_exception(scenario, "construct")
        if expected_exception:
            self._assert_expected_model_field_exception(
                expected_exception,
                lambda: self._construct_field(scenario.constructor_kwargs),
            )
            return

        field_instance = self._construct_field(scenario.constructor_kwargs)
        if scenario.post_construction:
            scenario.post_construction(field_instance)
        self._run_validators(
            scenario.construct_validators,
            field_instance,
            phase="construct",
            scenario=scenario,
        )

        expected_exception = self._expected_exception(scenario, "deconstruct")
        if expected_exception:
            self._assert_expected_model_field_exception(
                expected_exception,
                field_instance.deconstruct,
            )
            return

        deconstruction = field_instance.deconstruct()
        self._validate_deconstruction(deconstruction)
        self._run_validators(
            scenario.deconstruct_validators,
            deconstruction,
            phase="deconstruct",
            scenario=scenario,
        )

        if scenario.to_python_value is not _UNSET:
            expected_exception = self._expected_exception(scenario, "to_python")
            if expected_exception:
                self._assert_expected_model_field_exception(
                    expected_exception,
                    lambda: field_instance.to_python(scenario.to_python_value),
                )
                return

            result = field_instance.to_python(scenario.to_python_value)
            self._run_validators(
                scenario.to_python_validators,
                result,
                phase="to_python",
                scenario=scenario,
            )

        if scenario.get_prep_value is not _UNSET:
            expected_exception = self._expected_exception(scenario, "get_prep_value")
            if expected_exception:
                self._assert_expected_model_field_exception(
                    expected_exception,
                    lambda: field_instance.get_prep_value(scenario.get_prep_value),
                )
                return

            result = field_instance.get_prep_value(scenario.get_prep_value)
            self._run_validators(
                scenario.get_prep_value_validators,
                result,
                phase="get_prep_value",
                scenario=scenario,
            )

        if scenario.form_clean_value is not _UNSET:
            expected_exception = self._expected_exception(scenario, "form_clean")
            if expected_exception:
                self._assert_expected_model_field_exception(
                    expected_exception,
                    lambda: field_instance.formfield().clean(scenario.form_clean_value),
                )
                return

            result = field_instance.formfield().clean(scenario.form_clean_value)
            self._run_validators(
                scenario.form_clean_validators,
                result,
                phase="form_clean",
                scenario=scenario,
            )

    def _construct_field(
        self,
        constructor_kwargs: dict[str, Any] | Callable[[], dict[str, Any]],
    ) -> FieldType:
        """Construct the configured field from eager arguments or a factory."""
        if self.field_class is None:
            raise AssertionError("Model field test cases must define field_class")

        kwargs = (
            constructor_kwargs()
            if callable(constructor_kwargs)
            else constructor_kwargs
        )
        return self.field_class(**kwargs)

    @staticmethod
    def _expected_exception(
        scenario: ModelFieldScenario[FieldType],
        phase: Literal[
            "construct", "deconstruct", "to_python", "get_prep_value", "form_clean"
        ],
    ) -> ExpectedModelFieldException | None:
        """Return the exception expectation for one model-field phase, if any."""
        return next(
            (
                expected
                for expected in scenario.expected_exceptions
                if expected.phase == phase
            ),
            None,
        )

    def _assert_expected_model_field_exception(
        self,
        expected: ExpectedModelFieldException,
        operation: Callable[[], Any],
    ) -> None:
        """Assert an expected exception without database transaction handling."""
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
        scenario: ModelFieldScenario[FieldType],
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

    def _validate_deconstruction(
        self, deconstruction: tuple[str, str, list[Any], dict[str, Any]]
    ) -> None:
        """Confirm a field exposes a reusable Django migration representation."""
        _name, import_path, args, kwargs = deconstruction
        self.assertTrue(import_path)
        self.assertIsInstance(args, list)
        self.assertIsInstance(kwargs, dict)
