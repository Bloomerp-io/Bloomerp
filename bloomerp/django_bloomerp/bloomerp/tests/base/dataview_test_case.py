from django.test import SimpleTestCase

from bloomerp.dataviews.definition import DataviewTypeDefinition
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.tests.base.request_test_case_mixin import RequestScenario


class BloomerpDataviewTestCase(SimpleTestCase):
    """Base class providing common registry checks for a dataview."""

    dataview_key: str | None = None

    def get_test_scenarios(self) -> list[RequestScenario]:
        pass
    
    def get_dataview_definition(self) -> DataviewTypeDefinition:
        """Return the configured dataview definition."""
        definition = DATAVIEW_REGISTRY.get(self.dataview_key)
        if definition is None:
            raise AssertionError(f"Dataview {self.dataview_key!r} is not registered")
        return definition
    
    def test_dataview_is_valid(self) -> None:
        """
        Use case: An app registers a dataview implementation.
        Expected result: Its definition, renderer, and configuration are available.
        """
        # 1. Do not execute the reusable base class itself.
        if self.dataview_key is None:
            return

        # 2. Validate the registry wiring needed to render the dataview.
        definition = self.get_dataview_definition()
        self.assertEqual(definition.key, self.dataview_key)
        self.assertIsNotNone(definition.renderer_cls)
        self.assertIsNotNone(definition.config_cls)
