import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from bloomerp.models.automation.workflow import Workflow
from bloomerp.router import router
from bloomerp.serializers.workflow import WorkflowSerializer


@router.register(
    path="components/automation/save_workflow/",
    name="components_automation_save_workflow",
)
@require_POST
@login_required
def save_workflow(request: HttpRequest) -> HttpResponse:
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    workflow_id = payload.get("workflow_id")
    workflow = get_object_or_404(Workflow, id=workflow_id) if workflow_id else None

    serializer = WorkflowSerializer(instance=workflow, data=payload)
    if not serializer.is_valid():
        return JsonResponse(serializer.errors, status=400)

    workflow = serializer.save()
    status_code = 200 if workflow_id else 201
    response_data = WorkflowSerializer(workflow).data

    node_lookup = getattr(serializer, "_node_lookup", {})
    client_id_by_node_id = {
        node.id: client_id
        for client_id, node in node_lookup.items()
    }
    for node in response_data.get("nodes", []):
        node["client_id"] = client_id_by_node_id.get(node["id"], node["client_id"])

    return JsonResponse(response_data, status=status_code)
