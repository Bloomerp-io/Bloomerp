from rest_framework import serializers
from django.db import transaction

from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_edge import WorkflowEdge
from bloomerp.models.automation.workflow_node import WorkflowNode


def _node_reference_to_id(reference: str) -> int | None:
    if not reference.startswith("node-"):
        return None

    try:
        return int(reference.removeprefix("node-"))
    except ValueError:
        return None


def _safe_position(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class PositionIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if data in (None, ""):
            return self.default
        try:
            return super().to_internal_value(data)
        except serializers.ValidationError:
            return self.default


class WorkflowNodeSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    client_id = serializers.CharField(
        required=True,
        max_length=255,
    )
    type = serializers.ChoiceField(
        choices=WorkflowNode._meta.get_field("type").choices,
    )
    config = serializers.JSONField()
    pos_x = PositionIntegerField(required=False, allow_null=True, default=0)
    pos_y = PositionIntegerField(required=False, allow_null=True, default=0)
    
    def validate_config(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Node config must be an object.")
        if not value.get("sub_type"):
            raise serializers.ValidationError("Node config must include `sub_type`.")
        return value


class WorkflowEdgeSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    from_node = serializers.CharField(max_length=255)
    to_node = serializers.CharField(max_length=255)


class WorkflowSerializer(serializers.ModelSerializer):
    workflow_id = serializers.IntegerField(source="id", required=False)
    nodes = WorkflowNodeSerializer(many=True)
    edges = WorkflowEdgeSerializer(many=True)

    class Meta:
        model = Workflow
        fields = [
            "workflow_id",
            "name",
            "nodes",
            "edges",
        ]

    def validate(self, attrs):
        nodes = attrs.get("nodes", [])
        edges = attrs.get("edges", [])

        client_ids: set[str] = set()
        node_ids: set[int] = set()
        errors: dict[str, list[str]] = {}

        for node in nodes:
            client_id = node["client_id"]
            if client_id in client_ids:
                errors.setdefault("nodes", []).append(
                    f"Duplicate node client_id `{client_id}`."
                )
            client_ids.add(client_id)

            node_id = node.get("id")
            if node_id is not None:
                if node_id in node_ids:
                    errors.setdefault("nodes", []).append(
                        f"Duplicate node id `{node_id}`."
                    )
                node_ids.add(node_id)

        for index, edge in enumerate(edges):
            if edge["from_node"] not in client_ids:
                errors.setdefault("edges", []).append(
                    f"Edge {index} references unknown from_node `{edge['from_node']}`."
                )
            if edge["to_node"] not in client_ids:
                errors.setdefault("edges", []).append(
                    f"Edge {index} references unknown to_node `{edge['to_node']}`."
                )

        if errors:
            raise serializers.ValidationError(errors)

        instance: Workflow | None = getattr(self, "instance", None)
        if instance is not None:
            workflow_node_ids = set(instance.nodes.values_list("id", flat=True))
            invalid_node_ids = sorted(node_ids - workflow_node_ids)
            if invalid_node_ids:
                raise serializers.ValidationError(
                    {
                        "nodes": [
                            "Every node `id` must belong to the workflow being updated."
                        ]
                    }
                )

        return attrs

    def to_representation(self, instance):
        nodes = list(instance.nodes.all())
        node_key_map = {node.id: f"node-{node.id}" for node in nodes}

        return {
            "workflow_id": instance.id,
            "name": instance.name,
            "nodes": [
                {
                    "id": node.id,
                    "client_id": node_key_map[node.id],
                    "type": node.type,
                    "config": node.config,
                    "pos_x": node.pos_x,
                    "pos_y": node.pos_y,
                }
                for node in nodes
            ],
            "edges": [
                {
                    "id": edge.id,
                    "from_node": node_key_map[edge.from_node_id],
                    "to_node": node_key_map[edge.to_node_id],
                }
                for edge in WorkflowEdge.objects.filter(from_node__workflow=instance)
            ],
        }

    @transaction.atomic
    def create(self, validated_data):
        nodes_data = validated_data.pop("nodes", [])
        edges_data = validated_data.pop("edges", [])

        workflow = Workflow.objects.create(**validated_data)
        node_lookup = self._save_nodes(workflow, nodes_data)
        self._node_lookup = node_lookup
        self._replace_edges(workflow, edges_data, node_lookup)
        return workflow

    @transaction.atomic
    def update(self, instance, validated_data):
        nodes_data = validated_data.pop("nodes", [])
        edges_data = validated_data.pop("edges", [])

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        node_lookup = self._save_nodes(instance, nodes_data)
        self._node_lookup = node_lookup
        self._replace_edges(instance, edges_data, node_lookup)
        self._delete_removed_nodes(instance, node_lookup)
        return instance

    def _save_nodes(self, workflow: Workflow, nodes_data: list[dict]) -> dict[str, WorkflowNode]:
        node_lookup: dict[str, WorkflowNode] = {}

        for node_data in nodes_data:
            client_id = node_data["client_id"]
            node_id = self._resolve_node_id(workflow, node_data)
            node_values = {
                key: value
                for key, value in node_data.items()
                if key not in {"id", "client_id"}
            }
            node_values["pos_x"] = _safe_position(node_values.get("pos_x"))
            node_values["pos_y"] = _safe_position(node_values.get("pos_y"))

            if node_id is not None:
                node = workflow.nodes.get(id=node_id)
                for attr, value in node_values.items():
                    setattr(node, attr, value)
                node.save()
            else:
                node = WorkflowNode.objects.create(
                    workflow=workflow,
                    **node_values,
                )

            node_lookup[client_id] = node

        return node_lookup

    def _resolve_node_id(
        self,
        workflow: Workflow,
        node_data: dict,
    ) -> int | None:
        node_id = node_data.get("id")
        if node_id is not None:
            return node_id

        client_node_id = _node_reference_to_id(node_data["client_id"])
        if client_node_id is None:
            return None

        if workflow.nodes.filter(id=client_node_id).exists():
            return client_node_id

        return None

    def _replace_edges(
        self,
        workflow: Workflow,
        edges_data: list[dict],
        node_lookup: dict[str, WorkflowNode],
    ) -> None:
        WorkflowEdge.objects.filter(from_node__workflow=workflow).delete()

        new_edges = []
        for edge_data in edges_data:
            from_node_key = edge_data["from_node"]
            to_node_key = edge_data["to_node"]
            new_edges.append(
                WorkflowEdge(
                    from_node=node_lookup[from_node_key],
                    to_node=node_lookup[to_node_key],
                )
            )

        WorkflowEdge.objects.bulk_create(new_edges)

    def _delete_removed_nodes(
        self,
        workflow: Workflow,
        node_lookup: dict[str, WorkflowNode],
    ) -> None:
        kept_ids = {node.id for node in node_lookup.values()}
        workflow.nodes.exclude(id__in=kept_ids).delete()


EXAMPLE_WORKFLOW_PAYLOAD = {
    "name": "Send welcome email",
    "nodes": [
        {
            "client_id": "trigger-1",
            "type": "TRIGGER",
            "config": {
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {
                    "data": {
                        "email": "new.user@example.com",
                        "first_name": "Ava",
                    },
                },
            },
            "pos_x": 120,
            "pos_y": 80,
        },
        {
            "client_id": "action-1",
            "type": "ACTION",
            "config": {
                "sub_type": "SEND_EMAIL",
                "parameters": {
                    "recipient": "new.user@example.com",
                    "subject": "Welcome to Bloomerp",
                    "body": "Hi Ava, thanks for signing up.",
                },
            },
            "pos_x": 420,
            "pos_y": 80,
        },
    ],
    "edges": [
        {
            "from_node": "trigger-1",
            "to_node": "action-1",
        }
    ],
}


"""
Example usage:

serializer = WorkflowSerializer(data=EXAMPLE_WORKFLOW_PAYLOAD)
serializer.is_valid(raise_exception=True)
workflow = serializer.save()

update_payload = serializer.data
update_payload["name"] = "Send updated welcome email"
update_payload["nodes"][1]["config"]["subject"] = "Welcome aboard"

update_serializer = WorkflowSerializer(
    workflow,
    data=update_payload,
)
update_serializer.is_valid(raise_exception=True)
workflow = update_serializer.save()
"""
