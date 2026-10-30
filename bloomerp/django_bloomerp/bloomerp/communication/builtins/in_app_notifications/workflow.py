from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, Model, QuerySet
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.formats import date_format

from bloomerp.communication.builtins.in_app_notifications.base import (
    BaseSystemMessageType,
    SystemMessageItemData,
)
from bloomerp.utils.labels import safe_object_label

if TYPE_CHECKING:
    from bloomerp.models.automation.workflow_run import WorkflowRun
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


def _safe_absolute_url(obj: Model) -> str | None:
    try:
        return obj.get_absolute_url()
    except Exception:
        return None


def _snapshot_related_object(obj) -> dict | None:
    if not isinstance(obj, Model) or obj.pk is None:
        return None

    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    return {
        "content_type_id": content_type.pk,
        "object_id": str(obj.pk),
        "label": safe_object_label(obj),
        "type_label": str(obj._meta.verbose_name).title(),
        "url": _safe_absolute_url(obj),
    }


def _snapshot_run_view(
    workflow_run: WorkflowRun, execution_trace: list[dict] | None = None,
) -> dict:
    """Save the shared workflow canvas and run events without node parameters."""
    from bloomerp.serializers.workflow import WorkflowSerializer

    graph = dict(WorkflowSerializer(workflow_run.workflow).data)
    for node in graph["nodes"]:
        node.pop("parameters", None)

    if len({(node["pos_x"], node["pos_y"]) for node in graph["nodes"]}) == 1:
        for index, node in enumerate(graph["nodes"]):
            node["pos_y"] += index * 160

    trace = execution_trace or list(
        workflow_run.steps.order_by("sequence", "datetime_created").values("node_id", "status")
    )
    events = []
    for sequence, entry in enumerate(trace, start=1):
        if entry.get("node_id") is None:
            continue
        event = {
            "type": "workflow_run",
            "workflow_id": workflow_run.workflow_id,
            "run_id": workflow_run.pk,
            "node_id": int(entry["node_id"]),
            "sequence": sequence,
            "status": entry["status"],
        }
        events.append({**event, "event": "node.started"})
        status = entry["status"].lower()
        outcome = {"success": "completed", "error": "failed", "cancelled": "deferred"}.get(status, status)
        events.append({**event, "event": f"node.{outcome}"})
    return {"graph": graph, "events": events}


def _status_label(status: str) -> str:
    """Label persisted run states and legacy completion aliases consistently."""
    return {
        "success": "Completed",
        "successful": "Completed",
        "succeeded": "Completed",
        "completed": "Completed",
        "paused": "Approval required",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "queued": "Queued",
        "running": "Running",
    }.get(status.lower(), status.replace("_", " ").capitalize())


def _legacy_run_view(snapshot: dict) -> dict:
    """Adapt saved static graphs to the shared canvas without querying live nodes."""
    from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY

    graph = snapshot.get("graph") or {}
    nodes, events = [], []
    positions = {}
    for node in graph.get("nodes", []):
        node_id = int(node["id"])
        client_id = f"node-{node_id}"
        definition = WORKFLOW_NODE_REGISTRY.get(node.get("type", ""))
        positions[(node["x"] + 82, node["y"] + 28)] = client_id
        nodes.append({
            "id": node_id, "client_id": client_id,
            "name": node.get("label", ""),
            "type": definition.type if definition else "ACTION",
            "sub_type": node.get("type", ""),
            "pos_x": node["x"] * 1.5, "pos_y": node["y"] * 1.5,
        })
        for _ in range(node.get("execution_count", 0)):
            event = {
                "type": "workflow_run", "workflow_id": 0,
                "run_id": int(snapshot.get("workflow_run_id") or 0),
                "node_id": node_id, "status": node["status"],
            }
            events.append({**event, "event": "node.started"})
            events.append({**event, "event": f"node.{node['status']}"})
    edges = []
    for edge in graph.get("edges", []):
        source = positions.get((edge["x1"], edge["y1"]))
        target = positions.get((edge["x2"], edge["y2"]))
        if source and target:
            edges.append({"from_node": source, "to_node": target})
    return {"graph": {"nodes": nodes, "edges": edges}, "events": events}


def _duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    return max(0.0, (finished_at - started_at).total_seconds())


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes)}m {remaining:.0f}s"


class WorkflowSystemMessage(BaseSystemMessageType):
    @classmethod
    def build_item_data(cls, data: dict) -> SystemMessageItemData:
        """Persist a workflow result that remains readable after run cleanup."""
        from bloomerp.models.automation.workflow_run import WorkflowRun

        workflow_run_id = str(data["workflow_run_id"])
        workflow_run = WorkflowRun.objects.select_related("workflow").get(
            pk=workflow_run_id
        )
        steps = list(workflow_run.steps.order_by("sequence", "datetime_created"))
        execution_trace = list(data.get("execution_trace") or [])
        status = str(data.get("status") or "successful").lower()

        # Steps are written after their node executes, so the run timestamp is
        # the reliable start and the final step timestamp is the reliable end.
        started_at = workflow_run.datetime_created
        finished_at = (
            max(step.datetime_updated for step in steps)
            if steps
            else data.get("completed_at") or timezone.now()
        )
        duration_seconds = _duration_seconds(started_at, finished_at)
        finished_for_display = (
            timezone.localtime(finished_at)
            if timezone.is_aware(finished_at)
            else finished_at
        )
        status_label = _status_label(status)
        workflow = workflow_run.workflow

        snapshot = {
            "workflow_run_id": workflow_run_id,
            "workflow_name": workflow.name,
            "status": status,
            "status_label": status_label,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "finished_display": date_format(
                finished_for_display,
                "DATETIME_FORMAT",
            ),
            "duration_seconds": duration_seconds,
            "duration_display": _format_duration(duration_seconds),
            "step_count": len(execution_trace) or len(steps),
            "run_view": _snapshot_run_view(workflow_run, execution_trace),
            "approval_step_id": data.get("approval_step_id"),
            "approval_message": data.get("approval_message", ""),
            "related_object": _snapshot_related_object(data.get("related_object")),
            "run_url": _safe_absolute_url(workflow_run),
        }

        return SystemMessageItemData(
            title=(
                f"Approval required: {workflow.name}"
                if status == "paused"
                else f"Workflow '{workflow.name}' {status_label.lower()}"
            ),
            snippet=(
                snapshot["approval_message"]
                or f"{snapshot['step_count']} steps in {snapshot['duration_display']}"
            ),
            related_item_id=workflow_run_id,
            raw_meta_data={"workflow": snapshot},
        )

    @classmethod
    def render(cls, item: InboxItem, request: HttpRequest | None = None) -> str:
        """Reuse the workflow run canvas and the existing approval interaction."""
        from bloomerp.models.automation.workflow_run import WorkflowRun
        from bloomerp.automation.registry import WORKFLOW_NODE_REGISTRY
        from bloomerp.components.automation.approve_workflow_continuation import (
            can_approve_workflow_step,
        )

        snapshot = dict((item.raw_meta_data or {}).get("workflow") or {})
        snapshot["status_label"] = _status_label(snapshot.get("status", ""))
        workflow_run_id = snapshot.get("workflow_run_id") or item.related_item_id
        run = WorkflowRun.objects.select_related("workflow").filter(pk=workflow_run_id).first()
        run_view = snapshot.get("run_view") or _legacy_run_view(snapshot)
        approval_step = None
        if run and snapshot.get("approval_step_id"):
            approval_step = run.steps.select_related("node", "workflow_run__workflow").filter(
                pk=snapshot["approval_step_id"],
            ).first()
        if approval_step and approval_step.status != "PAUSED":
            snapshot["status_label"] = "Approval handled"
        can_approve = bool(
            request
            and approval_step
            and approval_step.status == "PAUSED"
            and can_approve_workflow_step(request.user, approval_step)
        )

        related_object = snapshot.get("related_object")
        if related_object:
            related_object = dict(related_object)
            related_object["available"] = False
            try:
                content_type = ContentType.objects.get_for_id(
                    related_object["content_type_id"]
                )
                model = content_type.model_class()
                related_object["available"] = bool(
                    model
                    and model._default_manager.filter(
                        pk=related_object["object_id"]
                    ).exists()
                )
            except (ContentType.DoesNotExist, KeyError, TypeError, ValueError):
                pass

        return render_to_string(
            "inbox_items/workflow_run.html",
            {
                "item": item,
                "workflow": snapshot,
                "run_available": run is not None,
                "workflow_readonly": True,
                "workflow_json": json.dumps(run_view.get("graph", {})),
                "workflow_run_events": json.dumps(run_view.get("events", [])),
                "workflow_run_status": snapshot["status_label"],
                "has_run_view": bool(run_view.get("graph", {}).get("nodes")),
                "node_types": WORKFLOW_NODE_REGISTRY.grouped(),
                "approval_step": approval_step,
                "approval_message": snapshot.get("approval_message") or (
                    (approval_step.node.parameters or {}).get("message", "")
                    if approval_step and approval_step.node else ""
                ),
                "can_approve": can_approve,
                "related_object": related_object,
            },
            request=request,
        )


def resolve_workflow_notification_folders(
    *,
    workflow_run_id: str,
    **kwargs,
) -> QuerySet:
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
    from bloomerp.models.automation.workflow_run import WorkflowRun
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    workflow_run = WorkflowRun.objects.select_related("workflow__created_by").get(
        pk=workflow_run_id
    )
    recipient_id = workflow_run.workflow.created_by_id
    if recipient_id is None:
        return InboxFolder.objects.none()

    return InboxFolder.objects.filter(
        Q(inbox__user_id=recipient_id)
        | Q(inbox__shared_with_users__id=recipient_id)
        | Q(inbox__shared_with_groups__user__id=recipient_id),
        inbox__source_object__isnull=True,
        type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key,
    ).distinct()


def handle_workflow_result(
    folders: QuerySet,
    *,
    workflow_run_id: str,
    status: str,
    execution_trace: list[dict] | None = None,
    related_object=None,
    completed_at=None,
    **kwargs,
):
    from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage
    from bloomerp.communication.inbox_sources import (
        InboxSourceDelivery,
        InboxSourceExecutionResult,
    )

    deliveries = []
    for folder in folders:
        item = SystemMessage.create_item(
            message_type="workflow",
            folder=folder,
            data={
                "workflow_run_id": workflow_run_id,
                "status": status,
                "execution_trace": execution_trace or [],
                "related_object": related_object,
                "completed_at": completed_at,
            },
        )
        deliveries.append(InboxSourceDelivery(folder=folder, items=(item,)))

    return InboxSourceExecutionResult(deliveries=tuple(deliveries))
