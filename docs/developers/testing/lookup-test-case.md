# Lookup test cases

Use `BloomerpLookupTestCase` for a lookup definition or bound lookup declared
in an app's `lookups` package. A `LookupScenario` checks the same lookup value
at the layers the lookup implements: the compiled Django query, optional SQL,
and optional in-memory evaluation.

This is the owner for lookup semantics. Test the model field's value conversion
in a [model field test case](model-field-test-case.md), and test an endpoint
that accepts a lookup filter in a [view test case](view-test-case.md).

## Generated skeleton

The generator creates one test module for every module-level `LookupDefinition`
or `BoundLookup` assignment it finds:

```python
from django.db.models import Q

from bloomerp.lookups.definition import CompiledLookup, CompiledSQL
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base import (
    BloomerpLookupTestCase,
    LookupScenario,
    PythonEvaluation,
)


class TestEqualsLookup(BloomerpLookupTestCase):
    lookup = equals_lookup

    def get_test_scenarios(self) -> list[LookupScenario]:
        return []
```

The base checks that `lookup` normalizes to a valid bound lookup with an ID.
It also provides dynamic-model fixtures and `get_application_field()` for a
field on `self.CustomerModel` by default.

## Compiled lookup scenario

Every scenario supplies the application field, field path, expression, value,
and the exact `CompiledLookup` expected from the lookup's Q factory.
`application_field` can be an `ApplicationField` or a zero-argument factory;
use a factory when preparation creates the field or its model context.

```python
LookupScenario(
    name="Matches an exact text value",
    application_field=lambda: self.get_application_field("first_name"),
    field_path="first_name",
    expression="equals",
    value="Ada",
    expected_lookup=CompiledLookup(predicate=Q(first_name="Ada")),
)
```

`preparation` runs before the application field is resolved. For non-nested
lookups, the base also confirms that `expression` is one of the lookup's
declared expressions. Nested lookups may accept expressions through their
nested definition instead.

Use the representation returned by the current lookup's Q factory for
`expected_lookup`; do not duplicate endpoint parsing or model-field conversion
rules in this test.

## Form value cleaning

When a lookup's form field normalizes a filter value, set `form_value` and
`expected_cleaned_form_value`. The base creates the form field with the
scenario's application field and compares its cleaned value exactly. Both
properties must be supplied together.

```python
LookupScenario(
    name="Normalizes an address filter",
    application_field=lambda: self.get_application_field("description"),
    field_path="address",
    expression="address_contains",
    value={"city": "Ghent"},
    form_value={"city": " Ghent "},
    expected_cleaned_form_value={"city": "Ghent"},
    expected_lookup=CompiledLookup(...),
)
```

## SQL and Python evaluation

Set `expected_sql` when the lookup supplies an SQL factory. The base invokes it
with `sql_context` (or a default context using `field_path`) and `sql_value`
(or `value` when omitted), then compares the result exactly.

```python
LookupScenario(
    name="Compiles case-insensitive matching for SQL and Python",
    application_field=lambda: self.get_application_field("first_name"),
    field_path="first_name",
    expression="iexact",
    value="ada",
    expected_lookup=CompiledLookup(predicate=Q(first_name__iexact="ada")),
    expected_sql=CompiledSQL(
        clause="LOWER(first_name) = LOWER(%s)",
        parameters=("ada",),
    ),
    python_evaluations=[
        PythonEvaluation(actual="Ada", expected=True),
        PythonEvaluation(actual="Grace", expected=False),
    ],
)
```

`python_evaluations` are optional. When present, the lookup must provide a
Python evaluator; each `actual` value is compared with the scenario's `value`
and asserted to produce `expected`. Likewise, an SQL expectation requires an
SQL factory. Leave either section out when that backend is not part of the
lookup contract.

Keep database filtering across real records, nested query composition, and
request parsing as focused integration tests when they would obscure the
lookup's direct compiled contract.
