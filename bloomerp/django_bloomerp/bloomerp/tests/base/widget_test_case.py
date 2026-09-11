from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from django import forms
from django.test import SimpleTestCase


WidgetType = TypeVar("WidgetType", bound=forms.Widget)


@dataclass(frozen=True)
class ExpectedWidgetException:
    """An exception expected while executing one widget operation."""

    exception: type[Exception] | tuple[type[Exception], ...]
    message_regex: str | None = None


@dataclass
class WidgetOperation(Generic[WidgetType]):
    """One named interaction with a widget and its result expectations."""

    name: str
    execute: Callable[[WidgetType], Any]
    result_validators: Callable[[Any], bool] | list[Callable[[Any], bool]] = field(
        default_factory=list
    )
    expected_exception: ExpectedWidgetException | None = None

    def __post_init__(self) -> None:
        """Reject result validators which cannot run after an expected failure."""
        if self.expected_exception is not None and self.result_validators:
            raise ValueError(
                "result_validators cannot be configured when the operation is "
                "expected to fail"
            )


@dataclass
class WidgetScenario(Generic[WidgetType]):
    """Declarative interactions with a Django widget.

    Constructor arguments can be eager values or zero-argument factories.
    Keyword arguments deliberately accept arbitrary objects, so widgets such as
    ``ForeignFieldWidget(model=SomeModel)`` can receive model classes directly.
    """

    name: str
    description: str | None = None
    preparation: Callable[[], None] | None = None
    constructor_args: tuple[Any, ...] | Callable[[], tuple[Any, ...]] = ()
    constructor_kwargs: dict[str, Any] | Callable[[], dict[str, Any]] = field(
        default_factory=dict
    )
    post_construction: Callable[[WidgetType], None] | None = None
    constructor_validators: Callable[[WidgetType], bool] | list[
        Callable[[WidgetType], bool]
    ] = field(default_factory=list)
    operations: list[WidgetOperation[WidgetType]] = field(default_factory=list)


class BloomerpWidgetTestCase(SimpleTestCase, Generic[WidgetType]):
    """Base class providing common validity checks for a Django widget."""

    widget_class: type[WidgetType] | None = None

    def get_widget_kwargs(self) -> dict[str, Any]:
        """Return constructor arguments for widgets that need custom setup."""
        return {}

    def test_widget_is_valid(self) -> None:
        """
        Use case: An app exposes a custom Django widget.
        Expected result: The widget is instantiable and declares a template.
        """
        # 1. Do not execute the reusable base class itself.
        if self.widget_class is None:
            return

        # 2. Validate and instantiate the configured widget.
        self.assertTrue(issubclass(self.widget_class, forms.Widget))
        widget = self.widget_class(**self.get_widget_kwargs())

        # 3. Ensure Django can identify the template used to render it.
        self.assertIsInstance(widget, forms.Widget)
        self.assertTrue(widget.template_name)

    def get_test_scenarios(self) -> list[WidgetScenario[WidgetType]]:
        """Return declarative widget scenarios for the concrete test case."""
        return []

    def test_widget_scenarios(self) -> None:
        """Run each scenario with a fresh widget instance and ordered operations."""
        if self.widget_class is None:
            return

        for scenario in self.get_test_scenarios():
            with self.subTest(name=scenario.name):
                self._run_widget_scenario(scenario)

    def _run_widget_scenario(self, scenario: WidgetScenario[WidgetType]) -> None:
        """Construct one widget and execute its operations in declaration order."""
        if scenario.preparation:
            scenario.preparation()

        widget = self._construct_widget(
            scenario.constructor_args,
            scenario.constructor_kwargs,
        )
        if scenario.post_construction:
            scenario.post_construction(widget)
        self._run_validators(
            scenario.constructor_validators,
            widget,
            subject="constructor",
            scenario=scenario,
        )

        for operation in scenario.operations:
            if operation.expected_exception:
                self._assert_expected_widget_exception(
                    operation.expected_exception,
                    lambda: operation.execute(widget),
                )
                return

            result = operation.execute(widget)
            self._run_validators(
                operation.result_validators,
                result,
                subject=f"operation {operation.name!r}",
                scenario=scenario,
            )

    def _construct_widget(
        self,
        constructor_args: tuple[Any, ...] | Callable[[], tuple[Any, ...]],
        constructor_kwargs: dict[str, Any] | Callable[[], dict[str, Any]],
    ) -> WidgetType:
        """Construct the configured widget from eager arguments or factories."""
        if self.widget_class is None:
            raise AssertionError("Widget test cases must define widget_class")

        args = constructor_args() if callable(constructor_args) else constructor_args
        kwargs = (
            constructor_kwargs()
            if callable(constructor_kwargs)
            else constructor_kwargs
        )
        return self.widget_class(*args, **kwargs)

    def _assert_expected_widget_exception(
        self,
        expected: ExpectedWidgetException,
        operation: Callable[[], Any],
    ) -> None:
        """Assert one expected widget operation exception without transactions."""
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
        subject: str,
        scenario: WidgetScenario[WidgetType],
    ) -> None:
        """Assert every validator configured for a successful widget result."""
        if callable(validators):
            validators = [validators]

        for validator in validators:
            validator_name = getattr(validator, "__name__", type(validator).__name__)
            description = f": {scenario.description}" if scenario.description else ""
            self.assertTrue(
                validator(value),
                f"{subject.capitalize()} validator {validator_name!r} failed for "
                f"scenario {scenario.name!r}{description}",
            )
