# Create a workflow

## Understand the user's goal

Start by asking in user-facing language: "What would you like this workflow to
achieve?" If the user has already stated the goal, acknowledge it and ask only
about missing details. Ask what should start the workflow, what information it
should use, and what result the user expects. For example: "When a new order
arrives, should we notify someone, update a record, or do something else?" Avoid
asking the user for node subtypes, schemas, model labels or other implementation
terms. Translate their answer into the available workflow nodes yourself.

Use the accompanying live `nodes` array to help the user design the workflow.
Explain suitable nodes by their names and descriptions, suggest a practical
sequence, and use parameter labels, help text, static choices, declared inputs,
outputs and ports to configure and connect them. Fill in what the user's goal
and the available metadata establish; ask focused questions for required values
that remain unknown. Do not invent unsupported capabilities, object IDs, dynamic
choices or defaults. If a needed capability is unavailable, explain the gap in
plain language and suggest an available alternative or a builder step. Describe
configuration-dependent uncertainties using `metadata_limits` and each node's
metadata status rather than claiming that the reference is exhaustive.

## Explain workflow settings

Explain these settings in plain language and help the user choose based on the
workflow's purpose:

- **Enable logging** (`enable_logging`): saves detailed execution history for
  workflow steps, including recorded inputs, outputs and errors, to help inspect
  what happened and troubleshoot problems. Logging adds storage and execution
  overhead; turning it off may improve performance and reduces detailed history.
  It does not disable basic run status tracking, and paused steps can still be
  persisted so a workflow can resume. The model default is off.
- **Run asynchronously** (`run_asynchronously`): queues the workflow for a
  background worker so the initiating request can return before the work finishes.
  This is useful for longer workflows where the user does not need the result
  immediately. A functioning task queue and worker are required; queuing a run
  does not mean it has completed. With this setting off, execution normally runs
  inline and the initiating request waits for it. A caller can explicitly override
  the execution mode. The model default is off.

Recommend a choice appropriate to the goal, explain the reason, and resolve any
uncertainty with the user. Neither setting starts a workflow. Creation, activation
and execution are separate actions; do not run the workflow merely to finish
creating it.

## Create with available tools

Use the mutation tools when available to create the workflow and its accompanying
nodes and connections. First consult `api_assistant_mutation_catalog` (or an
available equivalent) for the caller's permitted models, operations, required
fields and writable fields. Then use `api_assistant_mutations` according to its
advertised schema. Inspect the actual catalog before assuming that Workflow,
WorkflowNode or WorkflowEdge is exposed, writable, or accepts nested data.

Create the workflow record first and retain its returned ID. Create its nodes
using that workflow ID and the registered `type`, `sub_type` and `parameters`;
retain each returned node ID. Create connections using those node IDs and the
appropriate output port, if connection mutations are advertised. Set
`enable_logging` and `run_asynchronously` on the workflow using writable fields
in the advertised create or update contract. Generic mutations use model/object
IDs; the separate graph API below uses node client IDs. Do not mix the contracts.

A dedicated workflow tool may create the graph atomically if its advertised
schema supports that operation. Otherwise, if mutation tools cannot create some
part of the graph, use an available tool that explicitly supports the graph-save
API below, or help the user complete the missing part in the builder. Do not
pretend a resource read grants an HTTP execution capability. When only part of
the workflow is saved, retain the returned IDs, report exactly what remains, and
continue from those records rather than creating duplicates. Verify successful
tool results before reporting creation as complete.

The accompanying `nodes` array enumerates the live WORKFLOW_NODE_REGISTRY on
every read, including nodes registered by installed extensions. Use each entry's
`sub_type` and matching `type`; never assume a fixed list of available nodes.
TRIGGER nodes start runs, ACTION nodes perform work, and FLOW nodes route or
coordinate values. `parameters` belongs directly on a node, with keys matching
its configuration form fields. Configuration is not nested under `config`.

## Construction contract

The current checkout has no registered dedicated create_workflow MCP tool.
Inspect the available tool catalog on your instance;
if an extension provides one, follow its advertised input schema. Do not assume
that a generic object mutation accepts the nested graph payload below.

The existing authenticated graph creation API is POST
`/components/automation/save_workflow/` with JSON validated by WorkflowSerializer.
Creation requires UserPolicyManager's global `add_workflow` permission. Updates
include `workflow_id` and require object-level `change_workflow` access. Successful
creation returns 201 with the saved graph; updates return 200. Authentication and
the instance's CSRF requirements still apply when using the HTTP endpoint.
This graph serializer accepts only `workflow_id`, `name`, `nodes` and `edges`;
configure logging, asynchronous execution and activation through advertised
workflow mutation fields or the workflow settings editor, not this payload.

Payload structure (replace subtype, type and parameters with registry entries):

```json
{
  "name": "My workflow",
  "nodes": [
    {"client_id": "start", "type": "TRIGGER", "sub_type": "HUMAN_TRIGGER", "parameters": {"data": {}}, "pos_x": 0, "pos_y": 0},
    {"client_id": "next", "type": "ACTION", "sub_type": "WAIT", "parameters": {"wait_time": 1}, "pos_x": 300, "pos_y": 0}
  ],
  "edges": [{"from_node": "start", "to_node": "next", "output_port": "default"}]
}
```

Node `client_id` values must be unique. `type`, `sub_type`, `client_id` and an
object-valued `parameters` are required. `name` is optional; positions default to
zero. For updates, preserve node `id` values from the saved graph; each must belong
to that workflow. Edges reference node client IDs, not database IDs. Edge `name`
is optional, and `output_port` defaults to `default`. The serializer checks subtype
registration, matching types, edge endpoints, output ports and connection limits.
Graph updates replace the edge set and remove nodes omitted from the submitted
graph: submit the complete intended graph. Form validation and runtime behavior
can impose additional requirements beyond graph serializer validation.

## Values and connections

Each node receives its upstream output as input. The declared `input_requirement`
and `output_schema` describe declared baseline value types and fields.
`metadata_factory_overrides` identifies nodes whose form/schema/port factories
override those baseline facilities; their current contracts may differ even
before configuration. These factories are not called by the reference. Some schemas depend
on configured models, upstream data or selected ports; consult the authenticated
builder after configuring those nodes. Declared output ports have IDs and
`max_connections`; null allows unlimited connections. Nodes with no declared ports
receive an implicit unlimited `default` port. Conditional outputs must connect
using their named port IDs. For Each fans out to downstream work; Collect gathers
iteration results, and Merge Branches waits for upstream branches.

Executors using resolve_parameters support literal values, dotted template
references such as `{{ input.instance.email }}`, and structured references such
as `{"source": "input", "path": "instance.email"}`. A whole-string template
preserves the referenced value's type; references embedded in text stringify it.
Resolution recurses through objects and lists. Follow node help text for special
handling; not every executor resolves every parameter.

Use only object IDs and model choices that the caller is authorized to select.
Dynamic choices and callable defaults are intentionally omitted from this
reference. Creating or saving a graph does not constitute executing it. Review
side effects and activation/run settings in the workflow editor before running.

## Open the completed workflow in the builder

When creation is complete, use the available navigation tools to take the user
to the saved workflow's builder. Use the saved workflow ID and a verified
instance-local builder URL. The registered detail route is
`workflows_detail_builder`, normally `/automation/workflows/<workflow-id>/builder/`;
prefer a returned or resolved URL when available rather than guessing an ID or
using the workflow creation page.

Use `view_pages` when available to discover the user's connected browser tabs.
It excludes routes that require path arguments, so the saved workflow's builder
may not appear in its page catalog. Then call `navigate_user_mcp` (or an available
equivalent) with the builder URL. Supply the current conversation's known tab ID
when available; otherwise use the advertised navigation contract to select the
appropriate connected tab. Omitting `tab_id` navigates all connected tabs and
devices, so avoid doing so when a single appropriate tab can be identified.

Check the navigation result: distinguish a delivered or accepted command from a
confirmed completed navigation, and report partial failures accurately. If no
navigation tool or connected browser is available, provide the verified builder
link and explain how to open it. Summarize the created workflow in user-facing
language, including its purpose, chosen settings and any remaining configuration.
If creation is incomplete, opening the builder is a handoff for those remaining
steps; do not describe the workflow as finished.
