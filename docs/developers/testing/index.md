# Testing in Bloomerp

Bloomerp test cases are organized around the layer that owns the behavior.
Generated test files provide the correct base class, imports, route or class
metadata, and an empty scenario method. Developers then add only the scenarios
that describe meaningful behavior for that implementation.

The generator is a coverage scaffold, not a replacement for judgment. A
generated file proves that an implementation was discovered; its scenarios
should describe observable contracts rather than mirror every line of its
implementation.

## Generate test cases

Run the command from the Django project directory:

```bash
cd bloomerp/django_bloomerp
uv run python manage.py generate_test_cases bloomerp --dry-run
```

Replace `bloomerp` with one or more installed, local Django app labels. Use a
dry run first to inspect which files would be created or refreshed, then omit
`--dry-run` to write them.

Generate every supported category:

```bash
uv run python manage.py generate_test_cases bloomerp
```

Generate selected categories with a comma-separated list:

```bash
uv run python manage.py generate_test_cases bloomerp \
  --functionality=models,model_fields,form_fields,widgets
```

Supported values are:

- `views`
- `components`
- `models`
- `widgets`
- `workflow_nodes`
- `dataviews`
- `model_fields`
- `form_fields`

`--functionality=all` is equivalent to selecting every category. Hyphens in
category names are normalized to underscores.

The generator safely refreshes files that are still untouched skeletons. It
skips files containing authored test behavior. `--force` overwrites existing
files, including authored tests, so use it only when discarding those changes
is intentional.

## Testing philosophy

Choose the narrowest layer that owns the contract:

1. A widget presents a value and extracts raw submitted data.
2. A form field validates raw input and converts it to a Python value.
3. A model field converts Python values and prepares persistence data.
4. A model owns record lifecycle rules and model-level invariants.
5. A component or view owns one server-side HTTP interaction.
6. An end-to-end test owns browser wiring and a complete user journey.

Avoid repeating the same assertion at every layer. For example, a widget test
can check HTMX attributes, a component test can check the endpoint response,
and an end-to-end test can check that the browser actually sends the request
and swaps the result.

Prefer declarative scenarios when the behavior is a sequence already modeled
by the base test case. Use short lambdas for direct factories and boolean
checks. Use named bound methods for multi-step setup, shared state, context
managers, or assertions that read more clearly as statements. Keep specialized
integration tests as ordinary test methods when forcing them into a scenario
would obscure the behavior.

Scenarios should have specific names, create only the fixtures they need, and
validate outcomes rather than internal implementation details. Expected
failures belong on the operation that actually raises, not on an earlier setup
phase.

## Test-case guides

- [Model test cases](model-test-case.md)
- [Model field test cases](model-field-test-case.md)
- [Form field test cases](form-field-test-case.md)
- [Widget test cases](widget-test-case.md)
- [Request scenarios](request-test-case.md)
- [View test cases](view-test-case.md)
- [Component test cases](component-test-case.md)
- [Workflow node test cases](workflow-node-test-case.md)
- [Dataview test cases](dataview-test-case.md)
- [End-to-end test cases](e2e-test-case.md)

The channel and dynamic-model base classes are lower-level test utilities, not
generator targets. Use them for specialized websocket or integration tests
that do not fit one of the scenario-oriented bases above.
