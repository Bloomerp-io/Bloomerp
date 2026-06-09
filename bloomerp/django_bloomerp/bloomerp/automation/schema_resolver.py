from __future__ import annotations

from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.automation.schema import WorkflowIOSchema
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

    fields = []
    for schema in upstream_schemas:
        fields.extend(schema.fields)

    return WorkflowIOSchema(
        value_type="any",
        label="Multiple upstream outputs",
        description="This node receives output from multiple upstream nodes.",
        fields=fields,
    )


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
