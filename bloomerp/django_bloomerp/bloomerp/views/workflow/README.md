# Workflow Builder Notes

This folder contains the create/edit views that render the workflow builder.
The builder itself is split across a few layers:

- `views/workflow/create.py` and `views/workflow/edit.py` prepare the page context.
- `templates/cotton/workflow.html` renders the Drawflow canvas and node drawer.
- `static_src/ts/components/workflows/Workflow.ts` owns the frontend graph editor.
- `components/automation/render_workflow_node.py` renders node config forms and node metadata.
- `serializers/workflow.py` persists workflow nodes and edges.
- `services/workflow_services.py` executes workflows.

## Node Identity

The frontend uses Drawflow ids as `client_id` values such as `node-4`.
Persisted nodes also have database ids. During save, the serializer updates
existing nodes by `id` when available, and can recover existing nodes from
database-shaped client ids such as `node-14` when needed.

## Node Configuration

Each node stores config as:

```json
{
  "sub_type": "SEND_EMAIL",
  "parameters": {
    "recipient": "{{ input.item.email }}",
    "subject": "Hello",
    "body": "Hi {{ input.item.first_name }}"
  }
}
```

Executors expose a Django `config_form`, so the frontend can load config forms
through `/components/automation/render_workflow_node/`.

## Input Requirements And Output Schemas

Executors describe what they accept through `WorkflowInputRequirement` and what
they produce through `WorkflowIOSchema`. The builder uses the output schemas to
show clickable upstream value suggestions in the config modal, and can compare
upstream output schemas against the next node's input requirement.

Examples:

- `LIST_OBJECTS` accepts any input and outputs a list.
- `FILTER_OBJECTS` accepts a list and outputs a filtered list.
- `FOR_EACH` accepts a list and fans out downstream execution item by item.
- `IF_CONDITION` accepts any input and continues only when the condition is true.

## IF Condition MVP

`IF_CONDITION` is currently a condition gate, not a two-port true/false branch.
When the condition matches, the original input continues downstream. When it
does not match, the branch stops and the execution trace records
`branch_stopped`.

Adding explicit true/false branches later will likely require storing edge
ports, for example `from_output = "true"` or `from_output = "false"` on
`WorkflowEdge`.

## Execution Trace

`run_workflow(...)` returns a `WorkflowRun` and attaches an in-memory
`execution_trace` list for immediate debugging. The trace records each node id,
subtype, status, and output summary. Persisting this trace to the database is a
good next step once the run UI is ready.
