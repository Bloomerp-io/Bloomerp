# Generated model-field scenario pattern.
"""Check inherited labels remain virtual and read-only."""

from bloomerp.model_fields.labels_field import BloomerpLabelsField
from bloomerp.tests.base import BloomerpModelFieldTestCase, ModelFieldScenario


class TestBloomerpLabelsField(BloomerpModelFieldTestCase[BloomerpLabelsField]):
    """Exercise the field's declaration and migration representation."""

    field_class = BloomerpLabelsField

    def get_test_scenarios(self) -> list[ModelFieldScenario[BloomerpLabelsField]]:
        """Declare filterable metadata without an editable parent column."""
        return [
            ModelFieldScenario(
                name="Labels are a read-only virtual collection",
                construct_validators=[
                    lambda field: not field.editable,
                    lambda field: field.get_attname_column()[1] is None,
                ],
                deconstruct_validators=lambda definition: (
                    definition[1]
                    == "bloomerp.model_fields.labels_field.BloomerpLabelsField"
                ),
            )
        ]
