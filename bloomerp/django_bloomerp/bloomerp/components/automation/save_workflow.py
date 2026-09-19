import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from bloomerp.models.automation.workflow import Workflow
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.serializers.workflow import WorkflowSerializer


def _node_reference_to_id(reference: str) -> int | None:
    if not reference.startswith("node-"):
        return None

    try:
        return int(reference.removeprefix("node-"))
    except ValueError:
        return None


@router.register(
    path="components/automation/save_workflow/",
    name="components_automation_save_workflow",
)
@require_POST
@login_required
def save_workflow(request: HttpRequest) -> HttpResponse:
    """Endpoint to save a particular workflow
    
    Permissions based on whether the user has access to the workflow.

    Args:
        request (HttpRequest): the request object

    Returns:
        HttpResponse: the response
    """
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON body", status=400)

    workflow_id = payload.get("workflow_id")
    workflow = get_object_or_404(Workflow, id=workflow_id) if workflow_id else None
    
    policy_manager = UserPolicyManager(request.user)
    if not policy_manager.has_access_to_object(workflow, BloomerpPermission.CHANGE):
        return HttpResponse(status=403)
    
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

    for edge in response_data.get("edges", []):
        from_node_id = _node_reference_to_id(edge["from_node"])
        to_node_id = _node_reference_to_id(edge["to_node"])
        edge["from_node"] = client_id_by_node_id.get(from_node_id, edge["from_node"])
        edge["to_node"] = client_id_by_node_id.get(to_node_id, edge["to_node"])

    return JsonResponse(response_data, status=status_code)
