# Model base filters

Set `BloomerpModelConfig.base_filter` to a shared `Filter` to exclude records
from Bloomerp's application querysets. Its default is `None`, which preserves
existing behavior.

For example, a model with an `is_active` field can declare:

```python
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.definition import BloomerpModelConfig

model_config = BloomerpModelConfig(
    base_filter=Filter(
        connector="AND",
        conditions=[
            FilterCondition(
                field_path="is_active",
                lookup_id="equals",
                value=True,
            )
        ],
    )
)
```

Assign this configuration to the model's `bloomerp_config`. Use registered
lookup IDs and field paths supported by the shared filter system. Field
metadata must be synchronized as usual. Invalid fields or lookups raise an
error; they never silently disable the filter. Empty `AND` groups match all
rows, and empty `OR` groups match none.

The base filter intersects with row permissions and requested filters. It
applies to superusers as well as ordinary users, and it does not grant access.
It covers generated API reads and existing-object mutations (including nested
reads), dataviews, generic detail views, and the permission-manager querysets
used by bulk actions, search, exports and object access checks. Embedded
dataviews retain their supplied queryset's restrictions and also apply the
model base filter. Generic object actions and modal update/delete lookups use
the same rule; specialized file listings and mutation checks also honor a
base filter configured on `FileNode`.

Direct Django ORM access remains unchanged for internal lifecycle and future
restore operations. Custom application code can use
`apply_model_base_filter(queryset)` to narrow an existing queryset while
preserving its database, annotations and filters; it must still enforce user
permissions. Raw SQL is outside this queryset contract.

This is a selection rule, not a save validator: it does not prohibit creating
or updating a record so that it no longer matches. It introduces no draft or
soft-delete fields, retention behavior, migrations, or UI changes.
