from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from bloomerp.router import router
from bloomerp.services.workflow_node_rendering import (
    _get_node_sub_type,
    _workflow_node_schema_context,
    get_visible_workflow_node,
)


@csrf_exempt
@router.register(path='components/automation/render_workflow_node/', name='components_automation_render_workflow_node')
@login_required
def render_workflow_node(request: HttpRequest) -> HttpResponse:
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
    workflow_node = get_visible_workflow_node(request, node_id)
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
