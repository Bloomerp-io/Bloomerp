from __future__ import annotations

from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueField
from bloomerp.models.automation.workflow_edge import WorkflowEdge
from bloomerp.models.automation.workflow_node import WorkflowNode


def _get_node_sub_type(node: WorkflowNode):
    try:
        node_type = WorkflowNodeType.from_id(node.type)
    except ValueError:
        return None

    for sub_type in node_type.value.types:
        if node.node_sub_type_id == sub_type.id:
            return sub_type
    return None


def _node_input_key(node: WorkflowNode) -> str:
    return f"node_{node.id}"


def _namespace_schema_fields(
    fields: list[WorkflowValueField],
    prefix: str,
) -> list[WorkflowValueField]:
    remapped: list[WorkflowValueField] = []

    for field in fields:
        path = f"{prefix}.{field.path}" if field.path else prefix
        remapped.append(
            WorkflowValueField(
                path=path,
                label=field.label,
                value_type=field.value_type,
                description=field.description,
                optional=field.optional,
                children=_namespace_schema_fields(field.children, prefix),
            )
        )

    return remapped


def _build_multi_input_schema(
    incoming_edges: list[WorkflowEdge],
    upstream_schemas: list[WorkflowIOSchema],
) -> WorkflowIOSchema:
    fields: list[WorkflowValueField] = []

    for edge, schema in zip(incoming_edges, upstream_schemas):
        branch_prefix = _node_input_key(edge.from_node)
        branch_label = edge.from_node.node_sub_type.name if edge.from_node.node_sub_type else f"Node {edge.from_node.id}"
        fields.append(
            WorkflowValueField(
                path=branch_prefix,
                label=branch_label,
                value_type=schema.value_type,
                description=schema.description,
                children=_namespace_schema_fields(schema.fields, branch_prefix),
            )
        )

    return WorkflowIOSchema(
        value_type="object",
        label="Multiple upstream outputs",
        description="This node receives output from multiple upstream nodes.",
        fields=fields,
    )


def resolve_node_input_schema(
    node: WorkflowNode,
    seen_node_ids: set[int] | None = None,
) -> WorkflowIOSchema:
    seen_node_ids = seen_node_ids or set()
    incoming_edges = list(
        node.incoming_edges.select_related("from_node").order_by("id")
    )

    if not incoming_edges:
        return WorkflowIOSchema(
            value_type="none",
            label="No upstream input",
            description="This node has no incoming workflow edge.",
        )

    upstream_schemas = [
        resolve_node_output_schema(edge.from_node, seen_node_ids.copy())
        for edge in incoming_edges
    ]

    if len(upstream_schemas) == 1:
        return upstream_schemas[0]

    return _build_multi_input_schema(incoming_edges, upstream_schemas)


def resolve_node_output_schema(
    node: WorkflowNode,
    seen_node_ids: set[int] | None = None,
) -> WorkflowIOSchema:
    seen_node_ids = seen_node_ids or set()
    if node.id in seen_node_ids:
        return WorkflowIOSchema(
            value_type="any",
            label="Circular schema",
            description="A circular workflow connection prevented schema resolution.",
        )

    seen_node_ids.add(node.id)
    sub_type = _get_node_sub_type(node)
    if not sub_type or not sub_type.executor_cls:
        return WorkflowIOSchema(value_type="any", label="Output")

    input_schema = resolve_node_input_schema(node, seen_node_ids.copy())
    return sub_type.executor_cls.get_output_schema(node.config or {}, input_schema)
