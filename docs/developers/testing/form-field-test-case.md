# Form field test cases

Use `BloomerpFormFieldTestCase` for standalone custom Django form fields.
`FormFieldScenario` focuses on constructing the field and cleaning raw user
input into a validated Python value.

A model field controls persistence and database preparation. A form field owns
required checks, input validation, choices, and cleaning. A widget owns HTML
presentation and extraction of raw submitted values.

## Generated skeleton

```python
from bloomerp.form_fields.text_editor_field import TextEditorFormField
from bloomerp.tests.base import (
    BloomerpFormFieldTestCase,
    ExpectedFormFieldException,
    FormFieldScenario,
)


class TestTextEditorFormField(BloomerpFormFieldTestCase[TextEditorFormField]):
    field_class = TextEditorFormField

    def get_test_scenarios(self) -> list[FormFieldScenario[TextEditorFormField]]:
        return []
```

The base constructs the configured field and verifies that both the field and
its widget are Django form objects.

## Cleaning scenarios

Set `clean_value` to enable the clean phase. The runner calls
`field.clean(clean_value)` and passes its result to one validator or a list of
`clean_result_validators`. Explicit `None` is supported as a real test value.

```python
FormFieldScenario(
    name="Cleans rich text",
    clean_value="<p>Hello, world!</p>",
    clean_result_validators=lambda value: value == "<p>Hello, world!</p>",
)
```

Constructor positional and keyword arguments may be eager values or
zero-argument factories. `preparation` runs before those factories are
resolved. `post_construction` and `constructor_validators` receive the newly
constructed field.

Use lambdas for direct boolean checks. Use a named bound method when validation
needs several statements, a context manager, or fixtures stored on the test
case.

## Expected validation errors

Use `ExpectedFormFieldException` for `construct` or `clean` failures. Pass an
exception class or tuple and, optionally, a message regex.

```python
FormFieldScenario(
    name="Requires a value by default",
    clean_value="",
    expected_exceptions=[
        ExpectedFormFieldException(
            phase="clean",
            exception=ValidationError,
        )
    ],
)
```

Success validators cannot be combined with an expected exception for the same
phase. Once the exception is observed, that scenario stops.

Keep full `ModelForm` saving, cross-field form validation, request handling,
and browser interactions in their dedicated integration tests. A model-field
scenario may contain one form-clean check to verify that it selects the right
form field, but the standalone form-field test should own detailed cleaning
coverage.
