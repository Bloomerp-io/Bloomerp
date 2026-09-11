# Workflow node test cases

Use `BloomerpWorkflowNodeTestCase` for registered automation nodes. The base
verifies registry wiring, persists a node in a test workflow, executes it, and
checks its output or expected failure for every `WorkflowNodeScenario`.

## Generated skeleton

```python
from bloomerp.automation.actions.create_object import CreateObjectExecutor
from bloomerp.tests.base import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeScenario,
)


class TestCreateObjectNode(BloomerpWorkflowNodeTestCase):
    node_id = "CREATE_OBJECT"
    executor_class = CreateObjectExecutor

    def get_simulations(self) -> list[WorkflowNodeScenario]:
        return []
```

The configured executor class is checked against the registry. Override
`create_test_workflow()` only when the node needs a specialized workflow.

## Execution scenarios

`parameters` configures the persisted workflow node. `trigger_data` is passed
to its executor. Validate the result with an exact `expected_output`, one
`output_validators` callable, or a list:

```python
WorkflowNodeScenario(
    name="Creates an object from trigger data",
    parameters={
        "content_type_id": todo_content_type.pk,
        "data": {"title": "{{ input.title }}"},
    },
    trigger_data={"title": "Prepare report"},
    output_validators=lambda output: (
        output["status"] == "success"
        and Todo.objects.filter(title="Prepare report").exists()
    ),
)
```

Use `expected_exception` and optional `expected_exception_message` when
execution should fail. Do not combine an expected exception with an exact
expected output.

## Dynamic output schemas

When a node derives its output schema from its parameters or incoming schema,
set `input_schema`, then validate the result with `expected_output_schema` or
`output_schema_validators`. These checks call the executor's
`get_output_schema()` separately from execution.

The base creates application-field metadata during setup and uses a real test
database. Keep orchestration across several connected nodes, scheduling, and
browser editing of workflows in their broader integration or end-to-end test
layers.
