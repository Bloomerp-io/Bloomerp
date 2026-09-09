# Building workflow nodes

BloomERP workflow nodes are extensions of `BaseExecutor`. The workflow runtime does not switch on node IDs: an executor describes its configuration, schemas, output ports, and runtime behavior through a small public contract.

## A minimal node

```python
from django import forms

from bloomerp.automation import (
    BaseExecutor,
    WORKFLOW_NODE_REGISTRY,
    WorkflowIOSchema,
    WorkflowNodeDefinition,
)


class AddGreetingForm(forms.Form):
    greeting = forms.CharField(initial="Hello")


class AddGreetingExecutor(BaseExecutor):
    config_form = AddGreetingForm

    def execute(self, input_data):
        config = self.resolve_config(input_data)
        return {
            **input_data,
            "greeting": config["greeting"],
        }

    @classmethod
    def get_output_schema(
        cls,
        config=None,
        input_schema=None,
        port_id="default",
    ):
        return WorkflowIOSchema(value_type="object", label="Greeting data")


WORKFLOW_NODE_REGISTRY.register(
    "ADD_GREETING",
    WorkflowNodeDefinition(
        id="ADD_GREETING",
        type="ACTION",
        name="Add greeting",
        description="Adds a configured greeting to the input.",
        executor_cls=AddGreetingExecutor,
        icon="fa-solid fa-comment",
    ),
)
```

Register application nodes during Django application startup, normally in `AppConfig.ready()`. IDs must be globally unique. `type` must be `TRIGGER`, `ACTION`, or `FLOW`.

`execute()` may return any serializable Python value. That value is persisted when workflow logging is enabled and passed to every edge connected to the selected output port. Use `resolve_config(input_data)` when configuration may contain input references such as `{{ input.customer.id }}`.

## Inputs and output schemas

Declare an input contract with `input_requirement` or override `get_input_requirement(config)`. Declare a fixed `output_schema`, or override `get_output_schema(config, input_schema, port_id="default")` when the schema depends on configuration, upstream input, or the selected port.

The `port_id` argument is part of the node API even for single-output nodes. It lets a branch expose a different schema for each route:

```python
@classmethod
def get_output_schema(cls, config=None, input_schema=None, port_id="default"):
    if port_id == "invalid":
        return WorkflowIOSchema(value_type="object", label="Validation errors")
    return input_schema or WorkflowIOSchema(value_type="any")
```

Do not inspect incoming edges inside `get_output_schema()`. BloomERP resolves the upstream schema and passes it as `input_schema`.

## Output ports and branching

Executors that do not declare ports receive one implicit port:

```python
WorkflowNodeOutputPort(
    id="default",
    label="Output",
    max_connections=None,
)
```

The implicit default accepts any number of outgoing edges. This keeps ordinary action nodes simple and allows fan-out by drawing multiple edges.

For a fixed branch, declare ports on the executor and return a `RouteResult`:

```python
from bloomerp.automation import RouteResult, WorkflowNodeOutputPort


class ApprovalExecutor(BaseExecutor):
    output_ports = (
        WorkflowNodeOutputPort("approved", "Approved"),
        WorkflowNodeOutputPort("rejected", "Rejected"),
    )

    def execute(self, input_data):
        return RouteResult(
            port_id="approved" if input_data["approved"] else "rejected",
            output=input_data,
        )
```

`max_connections` defaults to `1`. Set it to a larger integer or `None` for an unlimited port. The model, API serializer, and builder all enforce the same limit. The selected port ID is stored on `WorkflowEdge.output_port`; it is not inferred from edge order or labels.

### Configuration-driven ports

Override `get_output_ports(config)` when users define branches in node configuration:

```python
@classmethod
def get_output_ports(cls, config=None):
    return tuple(
        WorkflowNodeOutputPort(
            id=branch["id"],
            label=branch["label"],
            max_connections=branch.get("max_connections", 1),
        )
        for branch in (config or {}).get("branches", [])
    )
```

Port IDs are persistent data. Use stable machine IDs and treat labels as display text. Renaming a label is safe; removing or changing an ID requires its existing edges to be removed or migrated. Returning duplicate or malformed IDs raises an error.

## Runtime result types

Most executors should return a normal value. Use a result object only to request orchestration behavior:

- `RouteResult(port_id, output)` sends one value through one named port.
- `FanOutResult(items, port_id="default")` runs the selected downstream branch once per item.
- `StopBranchResult(reason)` ends the current branch.
- `PauseResult(output)` creates a paused step that can be resumed later.


`prepare(input_data, context)` and `DeferResult` exist for advanced join nodes such as Collect and Merge Branches. Avoid them for normal actions and branches. A preparation hook may return `PreparedInput`, optionally changing the input or scope, or `DeferResult` when execution must wait for more arrivals. `WorkflowNodeExecutionContext` provides scoped transient storage and persisted-step output loading.

## Testing a node

Use `BloomerpWorkflowNodeTestCase` for executor contract tests:

```python
from bloomerp.automation import WorkflowIOSchema
from bloomerp.tests.base import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeSimulation,
)


class TestAddGreetingNode(BloomerpWorkflowNodeTestCase):
    node_id = "ADD_GREETING"
    executor_class = AddGreetingExecutor

    def get_simulations(self):
        input_schema = WorkflowIOSchema(value_type="object")
        return [
            WorkflowNodeSimulation(
                parameters={"greeting": "Hello"},
                trigger_data={"name": "Ada"},
                expected_output={"name": "Ada", "greeting": "Hello"},
                output_validators=[
                    lambda output: "greeting" in output,
                    lambda output: output["name"] == "Ada",
                ],
                input_schema=input_schema,
                output_schema_validators=[
                    lambda schema: schema.value_type == "object",
                ],
            )
        ]
```

Simulations call the node directly so failures identify the executor contract precisely. `input_schema` is supplied independently because output-schema resolution depends on upstream shape, not on a runtime value. Both validator fields accept one callable or a list.

For failure cases, set `expected_exception` and optionally `expected_exception_message`. Use `nodes` only when a direct simulation needs additional persisted nodes as fixtures; select orchestration behavior for a full workflow integration test instead.

Add a full `run_workflow()` integration test when the behavior involves routing, fan-out, pausing, joins, nested workflow execution, persistence, or edge cardinality. Those are runtime behaviors rather than isolated executor outputs.

At minimum, test:

- representative outputs and failures;
- input requirements and configuration-dependent output schemas;
- every named route and any dynamic port configuration;
- connection limits;
- orchestration results returned by the executor;
- side effects, retries, and transaction behavior where applicable.
