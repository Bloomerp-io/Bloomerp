# Behavior action test cases

Use `BloomerpBehaviorActionTestCase` for individual `BehaviorActionDefinition`
objects. Scenarios call `action.run()`, so they exercise the action's configuration
form and executor together. They do not call the HTTP endpoint or evaluate saved
rules, permissions, conditions, or listener/target eligibility. Those belong in
the execution-service and component tests.

## Generate scaffolds

From `bloomerp/django_bloomerp`, run:

```bash
uv run python manage.py generate_test_cases bloomerp --functionality=behavior_actions
```

The generator discovers module-level action definitions under an app's
`form_behaviors` package, including definitions not yet registered. Imported
re-exports do not create duplicate scaffolds. Empty files without action
definitions are ignored. Output mirrors the source directories under
`tests/form_behaviors`, with filenames such as
`builtins/test_hide_field_action.py`.

Generated classes set `action` and return an empty list from
`get_test_scenarios()`. The inherited definition check validates basic metadata
and callbacks; an empty scaffold does not demonstrate action behavior coverage.
As with other categories, authored files are preserved unless `--force` is used.

## Scenario API

Each `BehaviorActionScenario` accepts:

| Field | Purpose |
| --- | --- |
| `name` | Descriptive subtest name. |
| `description` | Optional context for failures. |
| `preparation` | Optional zero-argument setup callback. |
| `context` | `BehaviorContext`, or a zero-argument factory. |
| `config` | Raw configuration mapping, or a zero-argument factory; defaults to `{}`. |
| `listener`, `target` | Optional `ApplicationField` objects or zero-argument factories. |
| `expected_result` | Exact `BehaviorResult`, including values, states, and messages. |
| `expected_exception` | `ExpectedBehaviorActionException` with an exception class (or tuple) and optional `message_regex`. |

Supply exactly one of `expected_result` and `expected_exception`. Use
`BehaviorResult()` explicitly for an action that should produce no changes.
Configuration is passed through the same validation used by the action editor;
do not pre-clean configuration before supplying it to a scenario.

Preparation runs before factories are resolved. Setup failures are not accepted
as expected action exceptions. The base checks that the action leaves
`context.values` unchanged, including nested draft rows, on success or failure.
Scenarios run in named subtests and share the enclosing test's database fixtures;
use preparation to create any independent records a scenario needs.

The base provides the existing dynamic-model fixtures and
`get_application_field(field_name, model=None)`, which defaults to
`self.CustomerModel`. For targeted actions, supply both the target field name in
the context and the matching `ApplicationField` to `target`.

## Example scenario

This is an example to add when implementing an action's generated scaffold:

```python
from bloomerp.form_behaviors.builtins.hide_field import HIDE_FIELD
from bloomerp.form_behaviors.definition import (
    BehaviorContext,
    BehaviorResult,
    FieldStateUpdate,
)
from bloomerp.tests.base import BehaviorActionScenario, BloomerpBehaviorActionTestCase


class TestHideFieldAction(BloomerpBehaviorActionTestCase):
    """Verify hiding changes presentation while preserving the field value."""

    action = HIDE_FIELD

    def get_test_scenarios(self) -> list[BehaviorActionScenario]:
        """Describe the visibility update expected for a populated target."""
        return [
            BehaviorActionScenario(
                name="Hide last name without clearing its draft value",
                context=BehaviorContext(
                    values={"first_name": "Ada", "last_name": "Lovelace"},
                    listener_field="first_name",
                    target_field="last_name",
                ),
                listener=self.get_application_field("first_name"),
                target=self.get_application_field("last_name"),
                expected_result=BehaviorResult(
                    states=(FieldStateUpdate(field="last_name", visible=False),),
                ),
            ),
        ]
```

For invalid configuration, replace `expected_result` with
`ExpectedBehaviorActionException(exception=ValidationError, message_regex=...)`,
importing `ValidationError` from `django.core.exceptions` and
`ExpectedBehaviorActionException` from `bloomerp.tests.base`.
