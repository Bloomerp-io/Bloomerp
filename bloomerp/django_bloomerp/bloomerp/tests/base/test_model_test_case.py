from django.test import TestCase

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base.model_test_case import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)
from bloomerp.workspaces.analytics_tile.model import (
    AnalyticsTileConfig,
    AnalyticsTileType,
    FieldConfig,
)


class BloomerpModelTestCaseTests(TestCase):
    def test_model_scenario_supports_lazy_arguments_and_model_validators(self):
        """
        Use case: A scenario prepares data before resolving lifecycle arguments.
        Expected result: Lazy arguments and one-or-many validators remain declarative.
        """
        create_args = lambda: {"title": "Created"}
        update_args = lambda: {"title": "Updated"}
        validator = lambda instance: instance.pk is not None

        scenario = ModelScenario[Todo](
            name="todo lifecycle",
            preparation=lambda: None,
            create_args=create_args,
            create_validators=validator,
            update_args=update_args,
            update_validators=[validator],
        )

        self.assertIs(scenario.create_args, create_args)
        self.assertIs(scenario.update_args, update_args)
        self.assertIs(scenario.create_validators, validator)
        self.assertEqual(scenario.update_validators, [validator])

    def test_model_scenario_rejects_update_expectations_without_update_args(self):
        """
        Use case: A scenario defines expectations for an absent update operation.
        Expected result: The contradictory schema is rejected immediately.
        """
        with self.assertRaisesRegex(ValueError, "update_args"):
            ModelScenario[Todo](
                name="invalid update",
                expected_exceptions=[
                    ExpectedModelException(phase="update", exception=ValueError)
                ],
            )

    def test_model_scenario_rejects_duplicate_exception_phases(self):
        """
        Use case: A scenario defines two exception outcomes for one operation.
        Expected result: The ambiguous schema is rejected immediately.
        """
        with self.assertRaisesRegex(ValueError, "one entry per phase"):
            ModelScenario[Todo](
                name="ambiguous create failure",
                expected_exceptions=[
                    ExpectedModelException(phase="create", exception=ValueError),
                    ExpectedModelException(phase="create", exception=TypeError),
                ],
            )

    def test_model_scenario_defaults_are_not_shared(self):
        """
        Use case: Multiple model scenarios use default mutable collections.
        Expected result: Each scenario owns independent arguments and expectations.
        """
        first = ModelScenario[Todo](name="first")
        second = ModelScenario[Todo](name="second")

        self.assertIsNot(first.create_args, second.create_args)
        self.assertIsNot(first.create_validators, second.create_validators)
        self.assertIsNot(first.update_validators, second.update_validators)
        self.assertIsNot(first.expected_exceptions, second.expected_exceptions)

    def test_real_model_configuration_and_tiles_are_valid(self):
        """
        Use case: The shared model tests run against a configured Bloomerp model.
        Expected result: Todo's fields resolve and every declared tile is executable.
        """
        # 1. Configure the shared test case with a representative model.
        test_case = BloomerpModelTestCase()
        test_case.model = Todo
        config = test_case.get_model_config()
        self.assertIsNotNone(config)

        # 2. Validate every configured model-field reference.
        for field_name, source in test_case.get_configured_field_references(config):
            test_case.assert_model_has_field(field_name, source=source)

        # 3. Validate every tile, including executing analytics SQL.
        for tile in config.tiles:
            test_case.validate_tile(tile)

    def test_analytics_tile_query_and_output_fields_are_validated(self):
        """
        Use case: A model test validates an analytics tile.
        Expected result: Its SQL executes and configured output fields are present.
        """
        # 1. Define a self-contained analytics query and output field.
        tile = AnalyticsTileConfig(
            id="test:total",
            type=AnalyticsTileType.KPI.value.key,
            query="SELECT 1 AS total",
            fields={"value": [FieldConfig(name="total")]},
        )
        test_case = BloomerpModelTestCase()

        # 2. Validate the registered tile and execute its query.
        test_case.validate_tile(tile)

    def test_analytics_tile_rejects_unknown_output_fields(self):
        """
        Use case: An analytics tile references a field absent from its query.
        Expected result: The shared model test reports the invalid field.
        """
        # 1. Define a tile whose configured field is not selected by the query.
        tile = AnalyticsTileConfig(
            id="test:missing",
            type=AnalyticsTileType.KPI.value.key,
            query="SELECT 1 AS total",
            fields={"value": [FieldConfig(name="missing")]},
        )
        test_case = BloomerpModelTestCase()

        # 2. Confirm the mismatch produces an actionable assertion.
        with self.assertRaisesRegex(AssertionError, "missing"):
            test_case.validate_tile(tile)

    def test_model_configuration_fields_are_resolved(self):
        """
        Use case: Declarative model configuration references model fields.
        Expected result: Concrete fields and properties resolve; unknown fields fail.
        """
        # 1. Configure the helper with a real Bloomerp model.
        test_case = BloomerpModelTestCase()
        test_case.model = Todo

        # 2. Validate a concrete field and a model property.
        test_case.assert_model_has_field("title", source="test")
        test_case.assert_model_has_field("is_completed", source="test")

        # 3. Reject a field that cannot become an ApplicationField.
        with self.assertRaisesRegex(AssertionError, "unknown_field"):
            test_case.assert_model_has_field("unknown_field", source="test")
