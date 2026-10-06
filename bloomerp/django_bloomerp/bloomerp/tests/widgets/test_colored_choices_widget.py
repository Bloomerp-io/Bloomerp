"""Verify choice colors are safe and ordinary select semantics survive."""

from typing import Any
from django.http import QueryDict
from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetOperation, WidgetScenario
from bloomerp.widgets.colored_choices_widget import ColoredChoicesWidget


class TestColoredChoicesWidget(BloomerpWidgetTestCase[ColoredChoicesWidget]):
    """Test initial rendering and submitted values without database fixtures."""

    widget_class = ColoredChoicesWidget

    def _render(self, widget: ColoredChoicesWidget) -> str:
        """Render a selected value with valid, stale, and unsafe color settings."""
        return widget.render("status", "completed", attrs={"id": "id_status"})

    def _safe_markup(self, value: Any) -> bool:
        """Check selection, colors, component wiring and discarded unsafe metadata."""
        return (
            all(
                fragment in value
                for fragment in [
                    'bloomerp-component="colored-choices"',
                    'name="status"',
                    'value="completed" selected',
                    'data-choice-color="#00ff00"',
                    "border-left: 6px solid #00ff00",
                ]
            )
            and "javascript" not in value
            and "retired" not in value
        )

    def _extract(self, widget: ColoredChoicesWidget) -> Any:
        """Extract a submitted choice as a scalar like an ordinary Django select."""
        return widget.value_from_datadict(QueryDict("status=completed"), {}, "status")

    def _submitted_value(self, value: Any) -> bool:
        """Check that coloring does not change the submitted model value."""
        return value == "completed"

    def get_test_scenarios(self) -> list[WidgetScenario[ColoredChoicesWidget]]:
        """Cover initial colors, invalid metadata, and standard value extraction."""
        return [
            WidgetScenario(
                name="Colored select retains ordinary choice semantics",
                constructor_kwargs={
                    "choices": [("completed", "Completed"), ("scoped", "Scoped")],
                    "colors": {
                        "completed": "#00ff00",
                        "scoped": "javascript:unsafe",
                        "retired": "#ff0000",
                    },
                },
                operations=[
                    WidgetOperation(
                        name="Render safe colors",
                        execute=self._render,
                        result_validators=self._safe_markup,
                    ),
                    WidgetOperation(
                        name="Submit choice",
                        execute=self._extract,
                        result_validators=self._submitted_value,
                    ),
                ],
            )
        ]
