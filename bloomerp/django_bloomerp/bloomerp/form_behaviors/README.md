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
`config_form_factory(target, listener)` returns a Django form class.
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
  eligibility are checked. Collection actions currently require a superuser;
  parent-field permission must not substitute for child-row/column checks.
- Draft inputs and action outputs use the registered field validators. Partial
  rows are allowed; supplied columns are validated. Collection rows are capped
  at 1000 and persisted row IDs must belong to the current parent.
- Create-candidate row policies, nested permissions, dependency cascading, and
  relation resolvers remain separate work. This preview endpoint does not
  authorize a later save.
- ApplicationField configuration choices resolve within the action's queryset;
  other ModelChoiceField types are not supported by the draft binder.
- O2M updates match all active rows with the selected column value. The action
  does not fetch prices or infer which unsaved row changed.
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
