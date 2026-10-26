from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from bloomerp.router import router
from bloomerp.services.workflow_node_rendering import (
    _workflow_node_schema_context,
    get_visible_workflow_node,
)


@router.register(
    path='components/automation/render_workflow_node_schema_panel/',
    name='components_automation_render_workflow_node_schema_panel',
)
@login_required
def render_workflow_node_schema_panel(request: HttpRequest) -> HttpResponse:
    """Render schema and optional form only for a visible parent workflow."""
    node_id = request.GET.get("node_id")
    if not node_id:
        return HttpResponse("Missing workflow node id", status=400)

    workflow_node = get_visible_workflow_node(request, node_id)
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
