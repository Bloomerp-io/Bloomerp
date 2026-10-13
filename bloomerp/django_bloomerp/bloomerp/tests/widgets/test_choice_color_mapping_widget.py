"""Keep unmapped and retired choices out of editable color rows."""

from typing import Any

from django import forms

from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetOperation, WidgetScenario
from bloomerp.widgets.choice_color_mapping_widget import ChoiceColorMappingWidget


class TestChoiceColorMappingWidget(BloomerpWidgetTestCase[ChoiceColorMappingWidget]):
    """Use widget scenarios for restored and empty color mapping contexts."""

    widget_class = ChoiceColorMappingWidget

    def _restore(self, widget: ChoiceColorMappingWidget) -> dict[str, Any]:
        """Restore one current mapping while ignoring a retired key."""
        return widget.get_context(
            "colors", {"completed": "#00ff00", "retired": "#ff0000"}, None
        )

    def _current_rows(self, value: Any) -> bool:
        """Confirm unused choices stay available without acquiring a default color."""
        rows = value["widget"]["rows"]
        return (
            len(rows) == 1
            and "#00ff00" in rows[0]["right"]
            and "#ff0000" not in rows[0]["right"]
        )

    def _empty(self, widget: ChoiceColorMappingWidget) -> dict[str, Any]:
        """Render an entirely unmapped choice field."""
        return widget.get_context("colors", {}, None)

    def _no_rows(self, value: Any) -> bool:
        """Confirm users can add mappings and no empty colors silently become black."""
        return value["widget"]["rows"] == [] and value["widget"]["allow_adding_groups"]

    def get_test_scenarios(self) -> list[WidgetScenario[ChoiceColorMappingWidget]]:
        """Describe mapping rows independently from the endpoint and select widget."""
        return [
            WidgetScenario(
                name="Only explicitly configured current choices become color rows",
                constructor_kwargs={
                    "left": [("completed", "Completed"), ("scoped", "Scoped")],
                    "left_widget": forms.Select(
                        choices=[("completed", "Completed"), ("scoped", "Scoped")]
                    ),
                    "right_widget": forms.TextInput(attrs={"type": "color"}),
                    "allow_adding_groups": True,
                },
                operations=[
                    WidgetOperation(
                        name="Restore current rows",
                        execute=self._restore,
                        result_validators=self._current_rows,
                    ),
                    WidgetOperation(
                        name="Leave unmapped choices empty",
                        execute=self._empty,
                        result_validators=self._no_rows,
                    ),
                ],
            )
        ]
