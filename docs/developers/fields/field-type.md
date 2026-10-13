# Field types

`FieldTypeDefinition` declares a type's model integration, default editor behavior, and supported lookups. A lookup is available on a field only when its resolved field type includes it.

## Select lookups

Built-in lookups are ordinary `LookupDefinition` objects:

```python
from django.db import models

from bloomerp.field_types.registry import FieldTypeDefinition
from bloomerp.lookups.builtins import CONTAINS, EQUALS, VALUES_IN

TEXT = FieldTypeDefinition(
    id="ExampleText",
    label="Example text",
    model_field_cls=models.CharField,
    lookups=(EQUALS, CONTAINS, VALUES_IN),
)
```

`lookups` is the field's allow-list. Registering an operator globally does not automatically enable it on every field type.

The field registry uses two identifiers:

```python
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY

FIELD_TYPE_REGISTRY.register("EXAMPLE_TEXT", TEXT)

FIELD_TYPE_REGISTRY.EXAMPLE_TEXT      # Symbolic registration key
FIELD_TYPE_REGISTRY.from_id("ExampleText")  # Public field-type ID
```

Sharing `models.CharField` does not automatically replace the built-in `CharField` definition. Model metadata must select the declared variant. A custom Django field subclass can instead be associated with its own registered field type.

## Add an operator to a field type

When defining the field type, include the new lookup in its tuple:

```python
lookups=(EQUALS, CONTAINS, VALUES_IN, TEXT_LENGTH_GREATER_THAN)
```

For a built-in definition, this is an edit to that definition's declaration. Definitions are frozen, so appending to `CHAR_FIELD.lookups` at runtime is not supported.

There is currently no dedicated extension API for adding one lookup to an already-registered field type. An extension can replace a definition using `dataclasses.replace` and the registry's unregister/register operations, but this requires startup ordering and does not update references already held by other code. A public binding method is an unresolved API decision, not an implemented convenience function.

See [Writing a lookup](lookups.md) for the operator definition and lookup registry step.

## Model and analytics fields

The same type can describe different sources:

| Source                 | Metadata used to construct its default filter input                     |
| ---------------------- | ----------------------------------------------------------------------- |
| Model or dataview tile | The underlying `ApplicationField`, including its configured form field. |
| Analytics tile         | The mapped field type's standalone form factory.       |

An operator such as `equals` needs that default input: a choice field should present its choices, and a relation should present a record selector. An operator such as “length greater than” always needs an integer and can ignore the source metadata.

The current adapter between these sources is `FilterFieldContext`. Its role and limitations are explained in the [lookup guide](lookups.md#when-do-i-need-field-context).

## Nested fields

A relation's advanced lookup returns fields from the related model. A JSON-key lookup returns a free-form key selector. Neither compiles a Q or SQL predicate; the selected terminal lookup does that.

For example:

```text
Customer → Advanced → Name → Contains → "Bloom"
```

The resolver carries the full path while the input comes from the terminal name field's lookup. Current paths use `__`, and workspace roots include the tile identity, for example `tile_7:customer__name`.

The current path resolver requires a single unambiguous nested lookup at each traversed field. Supporting multiple traversal operations on one field requires a way to preserve the chosen operation in the path. JSON keys containing the path separator are also not yet representable unambiguously.

## Layout display options

`display_options` is a factory receiving the current `ApplicationField`. Resolve
it with `definition.get_display_options(application_field)`; an omitted factory
returns no options. This allows choices-dependent settings to disappear when
choices are removed from a field.

Each `FieldDisplayOption` uses a `form_factory` returning a fresh Django form
field, replacing `form_field_cls`, `form_field_kwargs`, and
`get_form_field_kwargs`:

```python
from django import forms

from bloomerp.models import ApplicationField
from bloomerp.field_types.display_options import FieldDisplayOption


def build_page_size(application_field: ApplicationField) -> forms.Field:
    """Create a bounded page-size editor for this field's layout."""
    return forms.IntegerField(min_value=1, max_value=100)


def display_options(application_field: ApplicationField) -> tuple[FieldDisplayOption, ...]:
    """Offer the page-size setting for this application field."""
    return (
        FieldDisplayOption(
            id="page_size",
            label="Page size",
            help_text="Choose the number of rows per page.",
            default=10,
            form_factory=build_page_size,
        ),
    )
```

Options provide label, help text, and `required=False` by default. A factory's
nonempty label and help text override the option metadata. Set `required=None`
on the option to keep the factory's required setting, or set it explicitly on
the option.

Built-in CharField and ChoiceField editors offer `choice_colors` when their
metadata contains choices. This mapping editor lets users add or remove entries and stores six-digit hex
colors in each layout item's configuration. Native selects display the current
choice's color accent in detail and create views. Retired choice keys are
ignored; fields without choices use an ordinary text input.
