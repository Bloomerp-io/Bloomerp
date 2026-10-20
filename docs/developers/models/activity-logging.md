# Conditional activity logging

Configure audit gates in a model's `BloomerpModelConfig.activity_log_settings`.
Existing models remain enabled with no conditions or ignored fields.

```python
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.definition import ActivityLogSettings, BloomerpModelConfig

bloomerp_config = BloomerpModelConfig(
    activity_log_settings=ActivityLogSettings(
        conditions=[
            Filter(
                connector="AND",
                conditions=[
                    FilterCondition(
                        field_path="status", lookup_id="equals", value="active",
                    ),
                ],
            ),
        ],
        ignored_change_fields=frozenset({"datetime_updated", "last_checked_at"}),
    ),
)
```

## Model-value conditions

`conditions` reuses the standard `Filter` and `FilterCondition` models, value
cleaning, field-specific lookup registry and Python evaluators. Groups are
combined with AND; each group's connector is AND or OR. An empty list and an
empty AND group match; an empty OR group does not.

Conditions apply to creation, changes and deletion. Values are captured before
the save/delete operation: conditions see the submitted concrete model values
(for partial saves, unchanged fields come from the existing database row).
Deletion conditions are evaluated while the row still exists. Conditions on
`auto_now` / `auto_now_add` timestamps are rejected because their final values do
not exist at capture time. Database defaults and triggers are not reflected in
this pre-save snapshot.

Only direct concrete model fields with a registered Python evaluator are
supported. Foreign-key conditions operate on the stored key, without loading the
related object. Relation traversal, reverse/many-to-many collections, virtual
properties and lookups without Python evaluation are not supported. The
`equals_user` / `$user` condition binds to the activity manager’s authenticated
request actor; without an authenticated actor it is a configuration error. This deliberately avoids hidden relation queries in every save.
Misconfigured fields/lookups/values log an error and retain the audit entry rather
than silently removing the audit trail. This is a logging preference, not an
access-control mechanism.

## Ignore changes that contain only bookkeeping

`ignored_change_fields` is a set of serializer/model field names. A CHANGE event
is skipped when its actual diff is empty or every changed field is in that set.
If any meaningful field changed, the full diff is retained, including associated
bookkeeping. CREATE and DELETE are never suppressed by this set (they still obey
`enabled` and `conditions`). `save(update_fields=...)` only contributes fields
actually included in that save, so unrelated dirty in-memory fields cannot make
a sync look like a configuration edit.

A normal model-value filter cannot express whether *only* bookkeeping fields
changed: filtering by an account's active status would also hide useful edits.
The separate actual-change gate handles this without inventing new filter
operators or changing filter semantics elsewhere.

EmailAccount uses this gate for `sync_cursor`, `next_sync_at`,
`last_sync_started_at`, `last_sync_finished_at`, `sync_locked_until`,
`datetime_updated` and `updated_by`. Repeated successful sync saves produce no
entries. Changes to `last_sync_error` (including clearing it), status, validation
results, sync settings and account configuration remain meaningful. As before,
`QuerySet.update()` bypasses Django save signals; this change does not add audit
coverage to those writes, including the sync-lock acquisition update.

## Performance and scope

Absent conditions resolve no filter metadata and perform no extra queries.
Ignored-only diffs return before creating an audit row. Configured conditions
reuse one resolver for all predicates in an event and use Python evaluation;
metadata/value cleaning may query, but no separate query tests the object against
a filtered queryset. Existing before/after serialization remains unchanged.
There is no process-wide cache of user-dependent lookup values.

These are code-level model settings; no database migration or new settings UI is
required. Existing activity storage, permissions and payload shapes are retained.
