"""Save a workflow graph through the authenticated, typed API."""

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from bloomerp.models.automation.workflow import Workflow
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.sdk.definition import SdkEndpoint
from bloomerp.serializers.workflow import WorkflowResponseSerializer, WorkflowSerializer
from bloomerp.views.api.base import BaseBloomerpApiView


@router.register(
    path="workflows/save/",
    route_type="api",
    url_name="workflows_save",
    sdk=SdkEndpoint(
        method="POST",
        input_serializer=WorkflowSerializer,
        output_serializer=WorkflowResponseSerializer,
    ),
)
class SaveWorkflowView(BaseBloomerpApiView):
    """Create or update a graph after enforcing workflow add/change access."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        """Persist validated nodes and edges while retaining the editor's client IDs."""
        if not isinstance(request.data, dict):
            raise ValidationError("Expected a workflow object.")
        workflow_id = None
        if "workflow_id" in request.data:
            workflow_id = WorkflowSerializer().fields["workflow_id"].run_validation(request.data["workflow_id"])
        workflow = get_object_or_404(Workflow, pk=workflow_id) if workflow_id is not None else None
        manager = UserPolicyManager(request.user)
        allowed = (
            manager.has_access_to_object(workflow, BloomerpPermission.CHANGE)
            if workflow is not None
            else manager.has_global_permission(Workflow, BloomerpPermission.ADD)
        )
        if not allowed:
            raise PermissionDenied()

        serializer = WorkflowSerializer(instance=workflow, data=request.data)
        serializer.is_valid(raise_exception=True)
        workflow = serializer.save()
        response_data = WorkflowResponseSerializer(workflow).data
        client_ids = {node.id: client_id for client_id, node in serializer._node_lookup.items()}
        references = {f"node-{node_id}": client_id for node_id, client_id in client_ids.items()}
        for node in response_data["nodes"]:
            node["client_id"] = client_ids.get(node["id"], node["client_id"])
        for edge in response_data["edges"]:
            for field in ("from_node", "to_node"):
                edge[field] = references.get(edge[field], edge[field])
        return Response(response_data, status=200 if workflow_id is not None else 201)
