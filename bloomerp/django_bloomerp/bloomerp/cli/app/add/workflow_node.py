# Proposed scaffolding parameters for an automation trigger, action, or flow node.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Symbolic WORKFLOW_NODE_REGISTRY registration key.
# id: str - Persisted WorkflowNodeDefinition.id.
# node_type: Literal["TRIGGER", "ACTION", "FLOW"] - Kind of workflow node.
# label: str - Human-readable WorkflowNodeDefinition.name.
# description: str - Guidance explaining the node's behavior.
# icon: str | None = None - Icon shown in the workflow builder.
# executor_cls: str | None = None - BaseExecutor subclass import path or scaffold.
# output_ports: tuple[str, ...] = () - Named executor output ports to scaffold.
# Registration: WORKFLOW_NODE_REGISTRY.register(key, definition).
