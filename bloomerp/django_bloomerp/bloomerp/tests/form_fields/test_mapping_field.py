from typing import Any

from django import forms
from django.core.exceptions import ValidationError

from bloomerp.form_fields.mapping_field import MappingField
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    ExpectedFormFieldException,
    FormFieldScenario,
)


class TestMappingField(BloomerpFormFieldTestCase[MappingField]):
    field_class = MappingField

    def matches_typed_mapping(self, value: Any) -> bool:
        """Verify the right field performs numeric conversion."""
        return value == {"Count": 3}

    def matches_multiple_values(self, value: Any) -> bool:
        """Verify a key can map to several validated choices."""
        return value == {"Applied": ["web", "email"]}

    def matches_empty_mapping(self, value: Any) -> bool:
        """Verify unused editors clean to an empty mapping."""
        return value == {}

    def get_test_scenarios(self) -> list[FormFieldScenario[MappingField]]:
        """Cover conversion, choice validation, completeness and uniqueness."""
        failure = [ExpectedFormFieldException(phase="clean", exception=ValidationError)]
        return [
            FormFieldScenario(
                name="Typed values",
                constructor_kwargs={"right_field": forms.IntegerField()},
                clean_value=[("Count", "3")],
                clean_result_validators=self.matches_typed_mapping,
            ),
            FormFieldScenario(
                name="Multiple values",
                constructor_kwargs={
                    "right_field": forms.MultipleChoiceField(
                        choices=[("web", "Website"), ("email", "Email")]
                    )
                },
                clean_value={"Applied": ["web", "email"]},
                clean_result_validators=self.matches_multiple_values,
            ),
            FormFieldScenario(
                name="Optional mapping",
                constructor_kwargs={"required": False},
                clean_value=[],
                clean_result_validators=self.matches_empty_mapping,
            ),
            FormFieldScenario(
                name="Unused fixed row",
                constructor_kwargs={"left": [("Count", "Count")], "required": False},
                clean_value=[("Count", "")],
                clean_result_validators=self.matches_empty_mapping,
            ),
            FormFieldScenario(
                name="Required mapping", clean_value=[], expected_exceptions=failure
            ),
            FormFieldScenario(
                name="Duplicate cleaned keys",
                clean_value=[(" Lane ", "one"), ("Lane", "two")],
                expected_exceptions=failure,
            ),
            FormFieldScenario(
                name="Incomplete row",
                clean_value=[("Lane", "")],
                expected_exceptions=failure,
            ),
            FormFieldScenario(
                name="Unknown right choice",
                constructor_kwargs={"right": [("web", "Website")]},
                clean_value={"Applied": "unknown"},
                expected_exceptions=failure,
            ),
            FormFieldScenario(
                name="Unknown fixed left choice",
                constructor_kwargs={"left": [("Count", "Count")]},
                clean_value={"Unknown": "value"},
                expected_exceptions=failure,
            ),
            FormFieldScenario(
                name="Malformed mapping",
                clean_value="[1, 2]",
                expected_exceptions=failure,
            ),
        ]
