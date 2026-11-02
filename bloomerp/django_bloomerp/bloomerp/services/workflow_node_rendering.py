from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY, WorkflowNodeDefinition
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from django import forms
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from bloomerp.automation.schema import WorkflowInputRequirement, flatten_schema_fields
from bloomerp.automation.schema_resolver import resolve_node_input_schema, resolve_node_output_schema

from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


def get_visible_workflow_node(request: HttpRequest, node_id: str) -> WorkflowNode:
    """Load node configuration only within the builder's parent Workflow view policy."""
    manager = UserPolicyManager(request.user)
    workflows = Workflow.objects.none()
    if manager.has_global_permission(Workflow, BloomerpPermission.VIEW):
        workflows = manager.get_accessible_queryset(Workflow, BloomerpPermission.VIEW)
    return get_object_or_404(
        WorkflowNode.objects.filter(workflow__in=workflows), pk=node_id
    )


class WorkflowConfigJSONForm(forms.Form):
    parameters = forms.JSONField(
        label="Config JSON",
        required=False,
        widget=CodeEditorWidget(language="json"),
        help_text="Edit this node's config parameters as JSON. Value references such as {{ input.instance.email }} can be used in strings.",
    )


def _get_node_sub_type(node_type: str | None, node_sub_type: str | None) -> WorkflowNodeDefinition | None:
    """Resolve a registered subtype belonging to the requested node type."""
    definition = WORKFLOW_NODE_REGISTRY.get(node_sub_type)
    if definition is None or definition.type != node_type:
        return None
    return definition


def _executor_input_requirement(executor_cls: type[BaseExecutor], config: dict) -> WorkflowInputRequirement:
    """Resolve the executor input requirement for the stored configuration."""
    if executor_cls and hasattr(executor_cls, "get_input_requirement"):
        return executor_cls.get_input_requirement(config)
    return WorkflowInputRequirement(value_type="any", label="Any input")


def _workflow_node_schema_context(
    workflow_node: WorkflowNode,
    request: HttpRequest,
    include_form: bool = False,
) -> dict:
    """Build schema and optional editing context for an authorized node."""
    selected_sub_type = workflow_node.node_sub_type
    if selected_sub_type is None or not selected_sub_type.executor_cls:
        return {}

    input_requirement = _executor_input_requirement(
        selected_sub_type.executor_cls,
        workflow_node.parameters or {},
    )
    incoming_schema = resolve_node_input_schema(workflow_node)
    output_schema = resolve_node_output_schema(workflow_node)
    output_paths = flatten_schema_fields(output_schema)

    # Check whether input is okay
    accepts_input = selected_sub_type.executor_cls.accepts_input_schema(
        incoming_schema,
        workflow_node.parameters,
    )

    # Build the form
    edit_mode = request.GET.get("edit_mode", "form")
    if edit_mode not in {"form", "json"}:
        edit_mode = "form"

    # Regular form
    parameters = dict(workflow_node.parameters or {})
    regular_form = selected_sub_type.executor_cls.get_config_form(initial=parameters)
    for field_name, field in regular_form.fields.items():
        if field_name not in parameters:
            initial = regular_form.get_initial_for_field(field, field_name)
            parameters[field_name] = initial if initial is not None else ""

    form = None
    if include_form:
        form = (
            WorkflowConfigJSONForm(initial={"parameters": parameters})
            if edit_mode == "json"
            else regular_form
        )

    return {
        "input_requirement": input_requirement,
        "incoming_schema": incoming_schema,
        "output_schema": output_schema,
        "output_paths": output_paths,
        "accepts_input" : accepts_input,
        "form": form,
        "edit_mode": edit_mode,
    }
