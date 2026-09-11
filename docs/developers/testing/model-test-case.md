# Model test cases

Use `BloomerpModelTestCase` for reusable checks on a Django model and for
declarative create, update, and delete scenarios.

The base class automatically validates the model's Bloomerp configuration and
workspace tiles. `ModelScenario` adds lifecycle-specific behavior without
requiring a separate test method for every straightforward case.

## Generated skeleton

The test-case generator creates the imports and scenario method needed to start:

```python
from bloomerp.models.project_management.initiative import Initiative
from bloomerp.tests.base import (
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)


class TestInitiativeModel(BloomerpModelTestCase):
    model = Initiative

    def get_test_scenarios(self) -> list[ModelScenario[Initiative]]:
        return []
```

## Lifecycle phases

Every scenario creates a model instance. Later phases are enabled by their
configuration:

- `create_args` always enables creation. It accepts a dictionary or a
  zero-argument factory returning a dictionary.
- `update_args` enables update when it is not `None`. An empty dictionary is
  useful when `post_create` has already changed the instance and the scenario
  only needs the runner to save it.
- Non-empty `delete_validators`, or an expected delete exception, enables
  deletion.

The runner refreshes the instance after successful creation and update. Each
validator receives that persisted instance and returns `True` on success. A
single validator or a list of validators is accepted.

```python
ModelScenario(
    name="Completed initiative can be reopened",
    create_args={
        "name": "Launch customer portal",
        "status": InitiativeStatus.COMPLETED,
    },
    create_validators=lambda initiative: initiative.completed_at is not None,
    update_args={"status": InitiativeStatus.IN_PROGRESS},
    update_validators=lambda initiative: initiative.completed_at is None,
)
```

## Preparation and related objects

`preparation` is a zero-argument callable executed before `create_args` is
resolved. Use it to create fixtures that the create-argument factory needs.
A bound method may store those fixtures on the test case.

`post_create` receives the newly created and refreshed instance. Use it when
related fixtures need the new instance as a foreign key.

```python
def create_started_todos(self, initiative: Initiative) -> None:
    Todo.objects.create(
        title="Review",
        initiative=initiative,
        status=TodoStatus.IN_REVIEW,
    )


ModelScenario(
    name="Initiative starts when an assigned to-do is active",
    create_args={"name": "Launch customer portal"},
    post_create=self.create_started_todos,
    create_validators=lambda initiative: initiative.has_started,
)
```

Prefer lambdas for short argument factories and boolean checks. Use a named
bound method for multi-step fixture creation, query-count contexts, or logic
that is clearer with statements.

## Expected exceptions

Use `ExpectedModelException` with the phase that contains the failing database
operation. Pass an exception class or tuple of classes, not an exception
instance. `message_regex` is optional.

```python
ModelScenario(
    name="Initiative rejects itself as parent",
    create_args={"name": "Launch customer portal"},
    post_create=lambda initiative: setattr(initiative, "parent", initiative),
    update_args={},
    expected_exceptions=[
        ExpectedModelException(
            phase="update",
            exception=ValidationError,
        )
    ],
)
```

The phase is `update` here because creation succeeds. The later `save()` is the
operation expected to raise. Once an expected exception is observed, the runner
does not execute later phases.

## Isolation

Every complete scenario runs in its own nested atomic block. Preparation and
all lifecycle changes are forced to roll back afterward, so fixtures and model
records cannot leak into the next scenario. Expected failing database
operations receive an additional savepoint so errors such as `IntegrityError`
do not leave the outer scenario transaction unusable.

Keep patch-heavy behavior, broad service integration, request behavior, and
complex query assertions as ordinary focused tests when forcing them into a
lifecycle scenario would hide the behavior being tested.
