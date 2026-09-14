# Writing a lookup

A lookup supplies three things:

1. An ID and label so users can select it.
2. An input for its expected value.
3. A factory for each execution backend it supports.

A lookup does not fetch a queryset, decide the user's permissions, or combine unrelated filter groups.

**Draft status:** the shared compiler now cleans values before invoking lookup factories. Typed model filters execute through Q or parameterized SQL; permission predicates reuse the same resolution and cleaning. Raw GET parsing and workspace execution remain unfinished. See [shared execution](execution.md).

## Example: text length greater than

The user selects a text field, chooses “Length greater than”, and enters an integer. The condition matches non-null strings longer than that integer.

The ORM example uses an expression directly, avoiding annotation-name allocation.

```python
from django import forms
from django.db.models import F, Q
from django.db.models.functions import Length
from django.db.models.lookups import GreaterThan

from bloomerp.lookups.definition import (
    CompiledLookup,
    CompiledSQL,
    FilterFieldContext,
    LookupDefinition,
    SQLLookupContext,
)


def length_input(context: FilterFieldContext) -> forms.IntegerField:
    # The input is always an integer; no source-field metadata is needed.
    return forms.IntegerField(min_value=0, label="Length")


def clean_length(value) -> int:
    # Defensive validation for callers invoking this factory directly.
    return forms.IntegerField(min_value=0).clean(value)


def length_q_factory(application_field, field_path, expression, value):
    length = clean_length(value)
    return CompiledLookup(
        predicate=Q(GreaterThan(Length(F(field_path)), length)),
    )


def length_sql_factory(context: SQLLookupContext, expression, value):
    length = clean_length(value)
    if context.dialect not in {"postgres", "sqlite"}:
        raise ValueError("Unsupported SQL dialect")
    return CompiledSQL(
        clause=f"LENGTH({context.field_path}) > %s",
        parameters=(length,),
    )


def length_evaluator(actual, expected):
    length = clean_length(expected)
    return actual is not None and len(actual) > length


TEXT_LENGTH_GREATER_THAN = LookupDefinition(
    id="text_length_greater_than",
    label="Length greater than",
    expressions=("text_length_greater_than",),
    default_form_factory=length_input,
    q_factory=length_q_factory,
    sql_factory=length_sql_factory,
    python_evaluator=length_evaluator,
)
```

`"Bloom"` matches an input of `4`; `"ERP"`, `""`, and `None` do not. Negative or missing lengths are invalid. The comparison is strictly greater than, not greater than or equal to.

The SQL field expression must come from the trusted resolver. Values go in `parameters`; never interpolate user-entered values into the clause.

## Register and enable it

Register the definition once during application startup:

```python
from bloomerp.lookups.registry import LOOKUP_REGISTRY

LOOKUP_REGISTRY.register(
    TEXT_LENGTH_GREATER_THAN.id,
    TEXT_LENGTH_GREATER_THAN,
)
```

Then include `TEXT_LENGTH_GREATER_THAN` in the target field type's `lookups` tuple. Both steps matter: the registry makes the definition discoverable by ID; the field type declares where it is supported.

For a built-in `CHAR_FIELD` declaration, that means adding the object alongside its existing text lookups. Runtime attachment to an existing registered type still needs a clearer public API; see [Field types](field-type.md#add-an-operator-to-a-field-type).

No special frontend branch should be needed for this integer input. That is the intended framework behavior; the replacement frontend is still being implemented.

## Factory contracts

| Hook | Receives | Returns |
| --- | --- | --- |
| `default_form_factory` | `FilterFieldContext` | A fresh Django `forms.Field`. |
| `q_factory` | `ApplicationField`, resolved ORM path, expression, value | `CompiledLookup`. |
| `sql_factory` | `SQLLookupContext`, expression, value | `CompiledSQL`. |
| `python_evaluator` | Actual value, expected value | Boolean. |

SQL and Python support are optional. A caller must reject unsupported execution rather than silently ignore the condition. A non-nested definition without a `q_factory` currently receives the default Django lookup factory, so omission does **not** mean “SQL-only”.

### IDs and expressions

`id` is the stable operator identifier stored in a condition. `label` is its user-facing text. `expressions` lists supported execution tokens and aliases.

Custom factories may ignore the expression argument, as the example does. Currently terminal lookups must still declare at least one expression. Nested lookups can use an empty tuple.

The default Q factory joins the field path and supplied expression. Only use it when that expression is a valid Django lookup; a custom ID such as `text_length_greater_than` needs a custom factory.

### ORM results

`CompiledLookup` contains:

- `predicate`: the Q expression to apply.
- `annotations`: optional expressions that must be attached before applying the predicate.
- `distinct`: whether duplicate rows must be removed.

The compiler must preserve all three. Annotation names cannot collide between conditions. No framework alias allocator exists yet; prefer a direct expression when possible, as in the example, rather than copying a fixed annotation name.

### SQL results

`CompiledSQL` contains a clause and an ordered tuple of parameters. `SQLLookupContext` contains the resolved field expression in `field_path`, optional SQL type and nullability metadata, and the dialect.

A lookup compiles a predicate fragment, not an entire query. Securing underlying tables and fields remains the permission layer's responsibility.

## When do I need field context?

Use it when the editor depends on the selected field. An equality editor can delegate to the default input:

```python
def equality_input(context: FilterFieldContext):
    return context.get_form_field()
```

The current context contains:

| Attribute | Purpose |
| --- | --- |
| `field_type` | The resolved field-type definition. |
| `application_field` | The underlying model field metadata, when available. |

`get_form_field()` first tries the application field's configured input. Without one, it calls the field type's `form_factory(FieldContext(), None)` and applies its `widget_factory`. A text input is the final fallback.

Analytics configuration only maps a column to a field type. For example, `total_spent` maps to `DECIMAL_FIELD`, whose factory constructs `forms.DecimalField()` without borrowing a source model's digit limits. The factory's second argument is the default form field Django constructed for a model-backed field; it is `None` for standalone analytics inputs.

The text-length editor does not need any of this metadata. Its parameter exists because all form factories use the same callable signature.

`FilterFieldContext` holds Python metadata. Its public serializer exposes only field-type and application-field IDs; factories receive the Python context. The public name remains `default_form_factory`, not the proposed `form_field_factory` spelling.

## Why return a form field instead of a widget?

A form field owns validation and conversion as well as its widget. `IntegerField.clean()` can convert an input string to an integer and reject negative values.

The shared compiler performs this validation before invoking a predicate factory, including for typed conditions that never used the UI. Direct calls to a factory bypass the compiler.

The compiler serializes native JSON before `forms.JSONField.clean()` and converts cleaned `ModelChoiceField` instances to primary keys. Custom structured widgets still need an explicit input contract; the framework does not guess how arbitrary objects should be decomposed.

## Nested lookups

A nested lookup selects another field rather than accepting a terminal comparison value:

```text
customer → foreign_advanced → name → contains → "Bloom"
```

Its definition declares `nested=True` and a `nested_fields_factory`. The current factory receives a root Django model and the resolved path, and returns `list[FilterFieldGroup]`.

Nested lookups cannot define Q factories, SQL factories, or Python evaluators, including through a `BoundLookup` override. The terminal lookup compiles the condition. Discovery factories return structural metadata; the user-facing resolver filters inaccessible fields separately.

This factory signature is still model-oriented. Supporting custom analytics structures cleanly, beyond the current JSON-key mechanism, is a reason to revisit its context argument.

“None of the related records match” is not simple navigation. It can instead be a terminal lookup whose value is an embedded filter expression and whose factory wraps that expression in `NOT EXISTS`. That operator is a future extension, not an existing built-in.

## Field-specific overrides

`BoundLookup` can override an existing operator's form factory or execution behavior while retaining its ID and label:

```python
from bloomerp.lookups.builtins import EQUALS
from bloomerp.lookups.definition import BoundLookup

CHOICE_EQUALS = BoundLookup(
    lookup=EQUALS,
    form_factory=lambda context: forms.ChoiceField(
        choices=(("retail", "Retail"), ("wholesale", "Wholesale")),
    ),
)
```

Several consumers already normalize through `BoundLookup`, but `FieldTypeDefinition.lookups` is currently annotated as a tuple of `LookupDefinition`. That mismatch should be resolved before presenting field-specific overrides as a stable extension contract. Do not register a `BoundLookup` in the global definition registry.

## Remaining API decisions

These are proposals to evaluate, not APIs available to import:

1. **Structured values:** extend the cleaning contract for custom composite widgets.
2. **Field metadata:** decide whether editor factories keep `FilterFieldContext` or receive the shared resolved field directly.
3. **Existing field-type extensions:** provide a supported way to attach a lookup without unregistering a frozen definition.
4. **Annotation allocation:** supply unique names from compilation context when a direct expression is insufficient.
5. **Expressions:** decide whether custom factories should need to repeat the lookup ID in `expressions`.
6. **Nested discovery:** settle a source-independent context and an unambiguous path representation.
7. **Value-free operators:** explicitly describe operators such as “today” that need no user input; currently some use hidden fields.

The target is a small authoring API: define an input, define supported predicates, register the operator, and declare the field types that allow it. The shared framework should handle the rest.
