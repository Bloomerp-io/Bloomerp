from typing import Any

from django import forms
from django.http import QueryDict

from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetOperation, WidgetScenario
from bloomerp.widgets.mapping_widget import MappingWidget


class TestMappingWidget(BloomerpWidgetTestCase[MappingWidget]):
    widget_class = MappingWidget

    def extract_multi_values(self, widget: MappingWidget) -> Any:
        """Extract multiple selected values with sparse row indices."""
        data = QueryDict(
            "mapping__rows=7&mapping__key_7=Applied&mapping__value_7=web&mapping__value_7=email"
        )
        return widget.value_from_datadict(data, {}, "mapping")

    def matches_multi_values(self, value: Any) -> bool:
        """Check that all selected values retain their mapping key."""
        return value == [("Applied", ["web", "email"])]

    def render_mapping(self, widget: MappingWidget) -> str:
        """Render saved values with independently named child inputs."""
        return widget.render(
            "mapping", {"Applied": ["web", "email"]}, attrs={"id": "id_mapping"}
        )

    def validates_rendered_mapping(self, value: Any) -> bool:
        """Check selected values, unique IDs and inert new-row markup."""
        return all(
            fragment in value
            for fragment in [
                'name="mapping__key_0"',
                'id="id_mapping__value_0"',
                'data-choice-label="Email" checked',
                "Website, Email",
                "data-mapping-up",
                "data-mapping-down",
                "data-mapping-key",
                "data-mapping-value",
                "data-mapping-selection",
                "data-mapping-template",
                "__prefix__",
            ]
        )

    def get_test_scenarios(self) -> list[WidgetScenario[MappingWidget]]:
        """Cover composable widgets through extraction and rendering scenarios."""
        return [
            WidgetScenario(
                name="One-to-many mapping",
                constructor_kwargs={
                    "right_widget": forms.SelectMultiple(
                        choices=[("web", "Website"), ("email", "Email")]
                    )
                },
                operations=[
                    WidgetOperation(
                        name="Extract values",
                        execute=self.extract_multi_values,
                        result_validators=self.matches_multi_values,
                    ),
                    WidgetOperation(
                        name="Render values",
                        execute=self.render_mapping,
                        result_validators=self.validates_rendered_mapping,
                    ),
                ],
            )
        ]
