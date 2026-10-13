"""Validate colors without rejecting mappings for retired choices."""

from typing import Any
from django import forms
from django.core.exceptions import ValidationError
from bloomerp.form_fields.choice_colors_field import ChoiceColorsField
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    ExpectedFormFieldException,
    FormFieldScenario,
)


class TestChoiceColorsField(BloomerpFormFieldTestCase[ChoiceColorsField]):
    """Cover validation and stale-key cleanup through form-field scenarios."""

    field_class = ChoiceColorsField

    def _valid_colors(self, value: Any) -> bool:
        """Check that only the current choice's valid color survives cleaning."""
        return value == {"completed": "#00ff00"}

    def _empty_colors(self, value: Any) -> bool:
        """Check that clearing all mappings produces an empty configuration."""
        return value == {}

    def get_test_scenarios(self) -> list[FormFieldScenario[ChoiceColorsField]]:
        """Describe valid, empty, invalid, duplicate, and malformed mappings."""
        kwargs = {
            "left": [("completed", "Completed")],
            "required": False,
            "right_field": forms.RegexField(regex=r"^#[0-9a-fA-F]{6}$"),
            "allow_adding_groups": False,
        }
        return [
            FormFieldScenario(
                name="Retired keys are ignored even with obsolete colors",
                constructor_kwargs=kwargs,
                clean_value='{"completed":"#00ff00","retired":"obsolete"}',
                clean_result_validators=self._valid_colors,
            ),
            FormFieldScenario(
                name="Empty rows clear colors",
                constructor_kwargs=kwargs,
                clean_value=[["completed", ""]],
                clean_result_validators=self._empty_colors,
            ),
            FormFieldScenario(
                name="Malformed color fails validation",
                constructor_kwargs=kwargs,
                clean_value={"completed": "red"},
                expected_exceptions=[
                    ExpectedFormFieldException(phase="clean", exception=ValidationError)
                ],
            ),
            FormFieldScenario(
                name="Duplicate current choices fail validation",
                constructor_kwargs=kwargs,
                clean_value=[["completed", "#00ff00"], ["completed", "#ff0000"]],
                expected_exceptions=[
                    ExpectedFormFieldException(phase="clean", exception=ValidationError)
                ],
            ),
            FormFieldScenario(
                name="Malformed mapping rows fail validation",
                constructor_kwargs=kwargs,
                clean_value=[["completed"]],
                expected_exceptions=[
                    ExpectedFormFieldException(phase="clean", exception=ValidationError)
                ],
            ),
        ]
