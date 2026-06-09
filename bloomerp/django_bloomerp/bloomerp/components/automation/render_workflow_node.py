from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.router import router
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from django import forms
from django.http import HttpResponse, HttpRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from bloomerp.automation.schema import WorkflowInputRequirement, flatten_schema_fields
from bloomerp.automation.schema_resolver import resolve_node_input_schema, resolve_node_output_schema


class WorkflowConfigJSONForm(forms.Form):
    parameters = forms.JSONField(
        label="Config JSON",
        required=False,
        widget=CodeEditorWidget(language="json"),
        help_text="Edit this node's config parameters as JSON. Value references such as {{ input.instance.email }} can be used in strings.",
    )


def _get_node_sub_type(node_type: str | None, node_sub_type: str | None):
    try:
        node = WorkflowNodeType.from_id(node_type)
    except ValueError:
        return None
    for sub_type in node.value.types:
        if node_sub_type == sub_type.id:
            return sub_type
    return None


def _executor_input_requirement(executor_cls: BaseExecutor, config: dict) -> WorkflowInputRequirement:
    if executor_cls and hasattr(executor_cls, "get_input_requirement"):
        return executor_cls.get_input_requirement(config)
    return WorkflowInputRequirement(value_type="any", label="Any input")


def _workflow_node_schema_context(
    workflow_node: WorkflowNode,
    request: HttpRequest,
    include_form: bool = False,
) -> dict:
    selected_sub_type = workflow_node.node_sub_type
    if selected_sub_type is None or not selected_sub_type.executor_cls:
        return {}

    input_requirement = _executor_input_requirement(
        selected_sub_type.executor_cls,
        workflow_node.config or {},
    )
    incoming_schema = resolve_node_input_schema(workflow_node)
    output_schema = resolve_node_output_schema(workflow_node)
    output_paths = flatten_schema_fields(output_schema)
    
    # Check whether input is okay
    accepts_input = selected_sub_type.executor_cls.accepts_input_schema(incoming_schema, workflow_node.config)
    
    # Build the form
    edit_mode = request.GET.get("edit_mode", "form")
    if edit_mode not in {"form", "json"}:
        edit_mode = "form"
    
    # Regular form
    config = workflow_node.config or {}
    parameters = config.get("parameters", {})
    regular_form = selected_sub_type.executor_cls.get_config_form(initial=parameters)
    for field in regular_form.fields:
        if field not in parameters:
            parameters[field] = ""
    
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


@csrf_exempt
@router.register(path='components/automation/render_workflow_node/', name='components_automation_render_workflow_node')
@login_required
def render_workflow_node(request:HttpRequest) -> HttpResponse:
    """Renders a workflow node for editing

    Args:
        request (HttpRequest): The HTTP request object.

    Returns:
        HttpResponse: The HTTP response object.
    """
    node_id = request.GET.get("node_id")
    if not node_id:
        return HttpResponse("Missing workflow node id", status=400)

    # Get the workflow node
    workflow_node = get_object_or_404(WorkflowNode, id=node_id)
    node_type = workflow_node.type
    node_sub_type = workflow_node.node_sub_type_id

    # Do some extra checks
    selected_sub_type = _get_node_sub_type(node_type, node_sub_type)
    if selected_sub_type is None:
        return HttpResponse("Unknown workflow node subtype", status=400)

    if not selected_sub_type.executor_cls or not selected_sub_type.executor_cls.config_form:
        return HttpResponse("This workflow node is not configurable yet.", status=400)

    schema_context = _workflow_node_schema_context(
        workflow_node,
        request,
        include_form=True,
    )
    
    return render(
        request,
        "components/automation/render_workflow_node.html",
        {
            "node_type": node_type,
            "node_sub_type": node_sub_type,
            "node_sub_type_definition": selected_sub_type,
            **schema_context,
        },
    )


@router.register(
    path='components/automation/render_workflow_node_schema_panel/',
    name='components_automation_render_workflow_node_schema_panel',
)
@login_required
def render_workflow_node_schema_panel(request: HttpRequest) -> HttpResponse:
    node_id = request.GET.get("node_id")
    if not node_id:
        return HttpResponse("Missing workflow node id", status=400)

    workflow_node = get_object_or_404(WorkflowNode, id=node_id)
    schema_context = _workflow_node_schema_context(
        workflow_node,
        request,
        include_form=request.GET.get("refresh_form") == "1",
    )
    if not schema_context:
        return HttpResponse("Unknown workflow node subtype", status=400)

    return render(
        request,
        "components/automation/workflow_node_schema_panel.html",
        schema_context,
    )
