from django.core.exceptions import ValidationError

from bloomerp.form_fields.text_editor_field import TextEditorFormField
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    ExpectedFormFieldException,
    FormFieldScenario,
)


class TestTextEditorFormField(BloomerpFormFieldTestCase):
    field_class = TextEditorFormField

    def get_test_scenarios(self) -> list[FormFieldScenario[TextEditorFormField]]:
        return [
            FormFieldScenario(
                name="cleans rich text",
                clean_value="<p>Hello, world!</p>",
                clean_result_validators=lambda value: value == "<p>Hello, world!</p>",
            ),
            FormFieldScenario(
                name="requires a value by default",
                clean_value="",
                expected_exceptions=[
                    ExpectedFormFieldException(
                        phase="clean",
                        exception=ValidationError,
                    )
                ],
            ),
        ]
