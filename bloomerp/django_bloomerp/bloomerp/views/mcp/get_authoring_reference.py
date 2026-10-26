"""Expose small live type indexes and targeted authoring contracts through MCP."""

from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from rest_framework import serializers
from rest_framework.response import Response

from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY
from bloomerp.mcp.definition import McpTool
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.views.mcp import workflows_resource
from bloomerp.views.mcp.workspaces_resource import tile_type_reference
from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY


class AuthoringReferenceRequestSerializer(serializers.Serializer):
    """Select an installed type, with optional parameters for dynamic node ports."""

    kind = serializers.ChoiceField(choices=("tile", "workflow_node"))
    type = serializers.CharField(required=False, max_length=255)
    parameters = serializers.DictField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Accept configuration only for a targeted workflow-node lookup."""
        if "parameters" in attrs and (
            attrs["kind"] != "workflow_node" or "type" not in attrs
        ):
            raise serializers.ValidationError(
                {"parameters": "Supply parameters only with kind=workflow_node and a type."}
            )
        return attrs


def authoring_type_index(kind: str) -> list[dict[str, str]]:
    """List live registered identities without building their configuration schemas."""
    if kind == "tile":
        return [
            {"type": key, "name": str(item.name), "description": str(item.description)}
            for key, item in TILE_TYPE_REGISTRY.items()
        ]
    return [
        {"type": item.id, "name": str(item.name), "description": str(item.description)}
        for item in WORKFLOW_NODE_REGISTRY.values()
    ]


@router.register(
    name="Get authoring reference",
    url_name="get_authoring_reference",
    route_type="mcp",
    description="Read a tile or workflow-node schema, or a compact index of installed types.",
    mcp=McpTool(
        title="Get authoring reference",
        description=(
            "Get one live tile or workflow-node authoring contract. If an existing object's "
            "tile type or node sub_type is known, pass it directly as type; omit type only "
            "to discover a compact index. Prefer this to loading the full creation guide "
            "for schema lookups. Workflow references include output ports and the exact "
            "string IDs to use in edge.output_port. Supply node parameters when ports "
            "depend on configuration. This tool does not create objects or execute workflows."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tile", "workflow_node"]},
                "type": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                    "description": "Registered tile type or workflow node sub_type; omit for an index.",
                },
                "parameters": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Optional workflow-node parameters used to resolve configured ports.",
                },
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tile", "workflow_node"]},
                "types": {"type": "array", "items": {"type": "object"}},
                "definition": {"type": "object"},
                "instructions": {"type": "string"},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def get_authoring_reference(request: HttpRequest) -> dict[str, Any] | Response:
    """Return permitted registry metadata without constructing tiles or running workflows."""
    if not request.user.is_authenticated:
        return Response({"detail": "Authentication required."}, status=401)
    serializer = AuthoringReferenceRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)
    arguments = serializer.validated_data
    kind = arguments["kind"]
    model = Workspace if kind == "tile" else Workflow
    if not UserPolicyManager(request.user).has_global_permission(model, [BloomerpPermission.VIEW]):
        return Response({"detail": "Access to this authoring reference is denied."}, status=403)

    type_id = arguments.get("type")
    if type_id is None:
        return {"kind": kind, "types": authoring_type_index(kind)}

    registry = TILE_TYPE_REGISTRY if kind == "tile" else WORKFLOW_NODE_REGISTRY
    definition = registry.get(type_id)
    if definition is None:
        return Response(
            {
                "type": "Unknown registered type. Omit type to discover available identities.",
                "suggested_arguments": {"kind": kind},
            },
            status=404,
        )
    if kind == "tile":
        reference = tile_type_reference(type_id, definition)
        instructions = (
            "Use config_schema for this tile's configuration, retaining its nested $defs. "
            "Retrieve the existing tile before editing and preserve unrelated configuration. "
            "Use the mutation catalog with model_label=bloomerp.Tile and the intended operation "
            "for permitted object fields. Query-dependent choices require permitted data lookup; "
            "this schema does not verify query results or render a tile."
        )
    else:
        try:
            reference = workflows_resource.targeted_node_reference(
                definition, arguments.get("parameters")
            )
        except (ValidationError, ValueError, TypeError, KeyError):
            return Response(
                {"parameters": "Cannot resolve output ports from these parameters. Check the node's declared fields."},
                status=400,
            )
        instructions = (
            "Use sub_type and type when creating a WorkflowNode; parameters describe its configuration. "
            "Use output_ports and connections when creating edges; output_port is an exact string ID. "
            "Respect each port's max_connections (null means unlimited). "
            "Configuration forms, dynamic choices, and input/output-schema factories are not run. "
            "The input/output schemas are declared baselines, not a resolved upstream/downstream contract. "
            "Use the mutation catalog for permitted node and edge object fields."
        )
    return {"kind": kind, "definition": reference, "instructions": instructions}
