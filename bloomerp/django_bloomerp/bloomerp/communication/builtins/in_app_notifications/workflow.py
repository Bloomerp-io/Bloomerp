from __future__ import annotations

from collections import defaultdict
from datetime import datetime

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


def _snapshot_graph(workflow, execution_trace: list[dict]) -> dict:
    from bloomerp.models.automation.workflow_edge import WorkflowEdge

    nodes = list(workflow.nodes.all().order_by("id"))
    # WorkflowEdge has no workflow FK, so derive its edges through the nodes.
    edges = list(
        WorkflowEdge.objects.filter(from_node__workflow=workflow).order_by("id")
    )

    traces_by_node: dict[str, list[dict]] = defaultdict(list)
    for entry in execution_trace:
        traces_by_node[str(entry.get("node_id"))].append(entry)

    raw_positions = {(node.pos_x, node.pos_y) for node in nodes}
    use_sequence_layout = len(nodes) > 1 and len(raw_positions) <= 1
    x_values = sorted({node.pos_x for node in nodes})
    y_values = sorted({node.pos_y for node in nodes})
    x_ranks = {value: index for index, value in enumerate(x_values)}
    y_ranks = {value: index for index, value in enumerate(y_values)}

    graph_nodes = []
    positions = {}
    for index, node in enumerate(nodes):
        if use_sequence_layout:
            graph_x = 32
            graph_y = 28 + index * 92
        else:
            graph_x = 32 + x_ranks.get(node.pos_x, 0) * 220
            graph_y = 28 + y_ranks.get(node.pos_y, 0) * 112

        node_traces = traces_by_node.get(str(node.id), [])
        if any(entry.get("status") == "error" for entry in node_traces):
            status = "failed"
        elif node_traces:
            status = "completed"
        else:
            status = "not_run"

        positions[str(node.id)] = (graph_x, graph_y)
        graph_nodes.append(
            {
                "id": str(node.id),
                "label": node.name or node.node_sub_type_id or "Workflow step",
                "type": node.node_sub_type_id or node.type,
                "status": status,
                "execution_count": len(node_traces),
                "x": graph_x,
                "y": graph_y,
            }
        )

    graph_edges = []
    for edge in edges:
        start = positions.get(str(edge.from_node_id))
        end = positions.get(str(edge.to_node_id))
        if not start or not end:
            continue
        graph_edges.append(
            {
                "x1": start[0] + 82,
                "y1": start[1] + 28,
                "x2": end[0] + 82,
                "y2": end[1] + 28,
            }
        )

    return {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "width": max((node["x"] for node in graph_nodes), default=0) + 200,
        "height": max((node["y"] for node in graph_nodes), default=0) + 90,
    }


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
        successful = status in {"success", "successful", "completed"}
        status_label = "Completed" if successful else "Failed"
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
            "graph": _snapshot_graph(workflow, execution_trace),
            "related_object": _snapshot_related_object(data.get("related_object")),
            "run_url": _safe_absolute_url(workflow_run),
        }

        return SystemMessageItemData(
            title=f"Workflow '{workflow.name}' {status_label.lower()}",
            snippet=(
                f"{snapshot['step_count']} steps in {snapshot['duration_display']}"
            ),
            related_item_id=workflow_run_id,
            raw_meta_data={"workflow": snapshot},
        )

    @classmethod
    def render(cls, item, request: HttpRequest | None = None) -> str:
        from bloomerp.models.automation.workflow_run import WorkflowRun

        snapshot = (item.raw_meta_data or {}).get("workflow") or {}
        workflow_run_id = snapshot.get("workflow_run_id") or item.related_item_id
        run_available = bool(
            workflow_run_id
            and WorkflowRun.objects.filter(pk=workflow_run_id).exists()
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
                "run_available": run_available,
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
