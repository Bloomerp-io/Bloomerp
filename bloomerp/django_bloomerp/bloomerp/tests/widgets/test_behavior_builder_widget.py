from bloomerp.tests.base import BloomerpWidgetTestCase, WidgetOperation, WidgetScenario
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget


class TestBehaviorBuilderWidget(BloomerpWidgetTestCase[BehaviorBuilderWidget]):
    widget_class = BehaviorBuilderWidget

    def get_test_scenarios(self) -> list[WidgetScenario[BehaviorBuilderWidget]]:
        return [
            WidgetScenario(
                name="Renders correctly with existing values",
            ),
            WidgetScenario(
                name="Renders correctly with new values"
            )
        ]
