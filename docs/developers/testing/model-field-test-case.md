# Model field test cases

Use `BloomerpModelFieldTestCase` for custom Django model fields. It verifies the
field's migration representation and can exercise its conversion pipeline with
`ModelFieldScenario`.

This layer tests persistence-oriented field behavior. Standalone user-input
validation belongs in a [form field test case](form-field-test-case.md), while
rendering and submitted-data extraction belong in a
[widget test case](widget-test-case.md).

## Generated skeleton

```python
from bloomerp.model_fields.address_field import AddressField
from bloomerp.tests.base import (
    BloomerpModelFieldTestCase,
    ExpectedModelFieldException,
    ModelFieldScenario,
)


class TestAddressField(BloomerpModelFieldTestCase[AddressField]):
    field_class = AddressField

    def get_test_scenarios(self) -> list[ModelFieldScenario[AddressField]]:
        return []
```

Every scenario constructs a fresh field and calls `deconstruct()`. The base
also checks that Django receives a reusable import path, positional arguments,
and keyword arguments for migrations.

## Optional phases

Set a phase's input value to enable it:

- `to_python_value` calls `field.to_python(value)` and passes the result to
  `to_python_validators`.
- `get_prep_value` calls `field.get_prep_value(value)` and passes the result to
  `get_prep_value_validators`.
- `form_clean_value` calls `field.formfield().clean(value)` and passes the
  result to `form_clean_validators`.

Omitting a value skips that phase. Explicit `None` is still a real input and
does not skip it.

```python
ModelFieldScenario(
    name="Normalizes an address for Python",
    to_python_value={
        "street_1": "  Main street 1  ",
        "postal_code": " 1000 ",
        "city": " Brussels ",
        "country": "be",
    },
    to_python_validators=[
        lambda value: value["street_1"] == "Main street 1",
        lambda value: value["country"] == "BE",
    ],
)
```

`construct_validators` receive the field instance.
`deconstruct_validators` receive Django's four-item deconstruction tuple.
Constructor keyword arguments may be a dictionary or zero-argument factory.
Use `preparation` before construction and `post_construction` when a field
needs additional setup after it exists.

## Form cleaning in a model field scenario

The form-clean phase is a small integration check for the form field selected
by the model field. Its input is the raw value normally produced by the widget;
its validators inspect the cleaned Python result.

For example, an address widget submits component values as a list, and the
address form field cleans them into a structured dictionary. Test detailed
form-field rules separately rather than repeating all of them here.

## Expected exceptions

Use `ExpectedModelFieldException` for failures during `construct`,
`deconstruct`, `to_python`, `get_prep_value`, or `form_clean`.

```python
ExpectedModelFieldException(
    phase="to_python",
    exception=ValidationError,
    message_regex="invalid value",
)
```

Do not configure success validators for a phase expected to fail. The runner
stops the scenario after the expected exception. Database-backed relations,
file storage, widgets, and full model-form workflows should remain specialized
tests.
