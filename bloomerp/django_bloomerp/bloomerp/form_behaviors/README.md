# Form behavior draft

`BehaviorActionDefinition` describes executable Python code. `BehaviorAction`,
`FormBehavior`, and `BehaviorConfig` are Pydantic declarations containing only
serializable data. Passing a definition as `action` normalizes it to its ID.
Field references in declarations use model field names, not database IDs.

```python
from bloomerp.form_behaviors.definition import (
    BehaviorAction,
    BehaviorConfig,
    FormBehavior,
)
from bloomerp.form_behaviors.builtins import POPULATE_WEEK_DATES
from bloomerp.models.definition import LayoutItem

item = LayoutItem(
    id="delivery_week",
    config={
        "behaviors": BehaviorConfig(
            behaviors=[
                FormBehavior(
                    id="populate_delivery_dates",
                    actions=[
                        BehaviorAction(
                            action=POPULATE_WEEK_DATES,
                            target_field="lines",
                            config={
                                "source": "delivery_week",
                                "column": "planned_date",
                                "days": 5,
                                "write_policy": "if_empty",
                            },
                        )
                    ],
                ),
            ]
        ).to_storage(),
    },
)
```

The containing layout field is the listener. `LayoutItem(behaviors=...)` is not
implemented; use `config` as shown. The builder and its form field use this versioned format exclusively.
No backward compatibility is provided.

- **Listener**: the field whose event triggers the behavior.
- **Source**: a field read by an action, selected in action configuration.
- **Target**: the field changed by the action.

`get_listener_fields(fields)` supplies eligible listeners.
`get_target_fields(fields, listener)` supplies eligible targets.
`config_form_factory(target, listener, request)` returns a Django form class.
`request` is the current `HttpRequest` on HTTP editor/execution paths and `None`
for explicitly headless validation. Execute callbacks receive
`(context, cleaned_data, user)`, where `user` is the current Django authenticated
user or `AnonymousUser` for public form execution.
`requires_target_field` controls whether a target selection is necessary.

The endpoint binds portable ApplicationField names through each configuration
form's ModelChoiceField queryset. JSON configuration values are serialized for
Django JSONField cleaning. Executors receive `cleaned_data`, which can contain
ApplicationField objects. Only registered actions can execute. The initial
registry includes the four sample actions; apps can explicitly call
`ACTION_REGISTRY.register(action.id, action)`. Automatic discovery is deferred.

## Request

POST JSON to `/components/form_behavior/execute/` with normal login and CSRF:

```json
{
  "preference_id": "saved-preference-id",
  "listener_field": "delivery_week",
  "event": "change",
  "revision": 12,
  "values": {
    "delivery_week": "2026-W38",
    "lines": []
  }
}
```

For editing an existing record include `object_id`. Use `form_id` instead of
`preference_id` for an authenticated Form-owned layout; supplying both is invalid.
The caller needs access to the Form and the target model. The preference must belong
to the caller. Definitions are read from its stored layout, never from request
JSON. Submit all values used by the selected behaviors, including current
collection values; omission of a condition/source is not treated as empty.

## Response

```json
{
  "revision": 12,
  "values": [
    {
      "field": "lines",
      "value": [
        {"planned_date": "2026-09-14"},
        {"planned_date": "2026-09-15"},
        {"planned_date": "2026-09-16"},
        {"planned_date": "2026-09-17"},
        {"planned_date": "2026-09-18"}
      ]
    }
  ],
  "states": [],
  "messages": []
}
```

The client will use the revision to reject stale results and apply values via
widget `setValue()`. No records are saved. Actions execute in declaration order;
each later action sees earlier value updates. Failure returns no partial batch.

## Deliberate draft boundaries

- Frontend transport/application, dependency cascades, and state restoration
  when a condition stops matching are not implemented.
- Conditions use the existing Filter schema and registered Python evaluators
  on top-level layout fields. Capability is determined by the lookup, not the
  field type: supported FK comparisons and O2M count lookups are available.
  Count lookups exclude draft rows marked `DELETE`; `count_equals = 0` checks
  for an empty active collection. Operators without Python evaluators and
  nested traversal are not offered and are rejected on save/execution.
- Model/global permissions, existing-object row access, field access, and action
  eligibility are checked. Collection actions currently require a superuser outside
  public Form submission previews; parent-field permission must not substitute for
  child-row/column checks. Action configuration can declare nested field references
  with distinct view/change requirements, which the executor authorizes centrally.
- Draft inputs and action outputs use the registered field validators. Partial
  rows are allowed; supplied columns are validated. Collection rows are capped
  at 1000 and persisted row IDs must belong to the current parent.
- Create-candidate row policies, nested permissions, dependency cascading, and
  multi-hop relation traversal remain separate work. This preview endpoint does not
  authorize a later save.
- ApplicationField configuration choices resolve within the action's queryset;
  other ModelChoiceField types are not supported by the draft binder.
- O2M updates copy `from_column` into `to_column` on all active draft rows.
  An optional one-hop `accessor` reads a compatible field from the selected
  related record (for example product.sales_price). The execution service
  batches record reads and enforces row and field visibility. Deleted rows
  and blank related sources are skipped. This does not identify the one row
  that changed; existing destination values on active rows are overwritten.
- `CALCULATE_O2M_ROW` is a targetless collection action that writes its listener
  value after calculating one numeric destination column per active row. Its
  restricted expression language accepts numeric child-column names, numeric
  literals, parentheses, unary signs, and `+`, `-`, `*`, `/`. It uses Decimal
  arithmetic, treats blank operands as zero, rejects destination self-reference,
  and requires view permission for sources plus change permission for the
  destination child column. Its write policy can recalculate always, only when
  the destination is empty, or when it is empty or numerically zero.
- `CALCULATE_FIELD` applies the same restricted Decimal expression engine to
  eligible top-level numeric source fields and writes one declared numeric,
  compatible text, or property target. Its listener can be any rendered field;
  the configured source references remain permission-aware, and the executor
  owns target authorization, coercion, validation, and serialization.
- Reusable expression parsing/evaluation, numeric eligibility, destination
  normalization, and scalar write decisions live under `shared/calculate.py`
  and `shared/write_policy.py`. Built-ins retain only their action-specific
  iteration, configuration relationships, and result construction.
- `CLEAR_VALUE` targets a normal top-level field and derives its empty public
  value from the registered form-field contract. This yields the appropriate
  scalar, boolean, relation, multi-value, or collection representation while
  retaining the executor's normal declared-target and write-access checks.
- `AGGREGATE_O2M_COLUMN` writes a top-level numeric target from one numeric
  child column using sum, nonblank count, first, or last. Deleted rows and blank
  operands are excluded; empty first/last results use the target's public empty
  value. Its backward-compatible write policy can always replace the target,
  write only when empty, or write when empty or numerically zero. Source view
  access and target change access are enforced by the executor.
- `DISABLE_FIELD` applies only `disabled=true` to its declared top-level target.
  Visibility and the draft value remain unchanged; the browser uses an inert
  container lock rather than disabling native controls, so submission retains
  the field value.
- `ENABLE_FIELD` symmetrically applies only `disabled=false`, restoring
  interaction without changing visibility or the draft value.
- `TRANSFORM_TEXT` reads a text listener and writes its declared text target.
  Uppercase, lowercase, and title case use Python's Unicode-aware string
  operations. Sentence case uppercases the first code point and lowercases the
  remainder without trimming. Trim removes only boundary whitespace; collapse
  whitespace replaces each Unicode whitespace run with one ordinary space and
  trims the boundaries. Slug uses Django's default ASCII `slugify`; snake case
  uses the same base, replaces separators with underscores, collapses repeated
  underscores, trims boundary underscores, and applies the selected case.
  Empty or `None` listeners propose an empty string, which the executor then
  normalizes through the declared target's registered form-field contract.
- Week population uses an explicit date column and either `if_empty` or explicit
  whole-collection `replace`. Persisted-row deletion and manual-override
  semantics must be settled before enabling replacement in a live editor.
- Saved configurations, the action `run()` helper, and execution all bind
  portable JSON configuration through `clean_action_config`. The editor uses
  the same underlying form factory and field-name choices.

## Draft editor

Field display options now mount the versioned behavior builder. Add, remove,
and reorder behaviors and actions; choose events and optional filter groups.
`FormBehavior.conditions` stores a list of `Filter` groups. Conditions within
each group use its AND/OR connector; groups combine with AND, matching the
shared filtering system. An empty list runs unconditionally.
The complete shared filter editor is embedded with top-level draft
fields and Python-evaluable lookups. Action selection comes from the registry.
Choose a target before loading its Django configuration form. Form submission
collects widget values into the hidden JSON field and validates action forms
on the server. This enables configuration authoring; browser execution of
these new declarations remains separate work.

## Execution service

`BehaviorExecutor(owner, user, instance=...).evaluate(listener_field, values,
event="change")` returns a `BehaviorResult` with no database writes. The service
checks layout ownership/access, model and field permissions, validates values,
evaluates filter groups, and executes actions in order on a private draft.
The endpoint only parses the request, resolves authorized owner/object IDs,
and serializes the result with the request revision.

## Dynamic action configuration

The factory continues to return a Django form **class**. Declare
`refresh_fields = ("from_column", "to_column")` on that class. The editor sends
current partial values as `initial` when re-rendering; the form's `__init__`
owns dependent fields, querysets, choices, and resetting stale initial values.
No refresh metadata is stored in the saved behavior configuration.

Selects and checkboxes refresh after selection. Text edits refresh after leaving
the field and only when the value changed. Widget events emitted during typing
are deferred. Incomplete required values do not block a configuration refresh.
Other fields are preserved, obsolete requests are cancelled, and saving is blocked
until the latest fragment has loaded. Forms without `refresh_fields` do not refresh.

The same initialization runs when binding saved configuration for validation.
Raw submitted values remain separate from `initial`: resetting an editor's
initial accessor does not silently accept an invalid accessor on save.
`SET_O2M_VALUE` restricts compatible choices using field type and related-model
identity, and requires an accessor when a direct copy is incompatible.
