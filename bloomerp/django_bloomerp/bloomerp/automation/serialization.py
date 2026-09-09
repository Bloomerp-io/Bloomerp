"""Serialization helpers shared by workflow services and run models."""

from dataclasses import asdict, is_dataclass

from django.apps import apps
from django.db.models import Model
from django.db.models.query import QuerySet

from bloomerp.automation.results import (
    DeferResult,
    FanOutResult,
    RouteResult,
    StopBranchResult,
)
from bloomerp.utils.json_serialization import make_json_safe


OUTPUT_UNSET = object()


def serialize_workflow_value(value):
    if isinstance(value, FanOutResult):
        return {
            "__workflow_value__": "fan_out_result",
            "items": serialize_workflow_value(value.items),
            "port_id": value.port_id,
        }
    if isinstance(value, RouteResult):
        return {
            "__workflow_value__": "route_result",
            "port_id": value.port_id,
            "output": serialize_workflow_value(value.output),
        }
    if isinstance(value, StopBranchResult):
        return {
            "__workflow_value__": "stop_branch_result",
            "reason": value.reason,
        }
    if isinstance(value, DeferResult):
        return {
            "__workflow_value__": "defer_result",
            "output": serialize_workflow_value(value.output),
        }
    if isinstance(value, Model):
        return {
            "__model__": value._meta.label_lower,
            "pk": make_json_safe(value.pk),
        }
    if isinstance(value, type) and issubclass(value, Model):
        return {"__model_class__": value._meta.label_lower}
    if isinstance(value, QuerySet):
        return [serialize_workflow_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): serialize_workflow_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [serialize_workflow_value(item) for item in value]
    if is_dataclass(value):
        return serialize_workflow_value(asdict(value))
    return make_json_safe(value)


def deserialize_workflow_value(value):
    if isinstance(value, dict):
        workflow_value = value.get("__workflow_value__")
        if workflow_value == "fan_out_result":
            return FanOutResult(
                items=deserialize_workflow_value(value.get("items", [])),
                port_id=value.get("port_id", "default"),
            )
        if workflow_value == "route_result":
            return RouteResult(
                port_id=value.get("port_id", "default"),
                output=deserialize_workflow_value(value.get("output")),
            )
        if workflow_value == "stop_branch_result":
            return StopBranchResult(reason=value.get("reason", "Branch stopped"))
        if workflow_value == "defer_result":
            return DeferResult(output=deserialize_workflow_value(value.get("output")))

        model_label = value.get("__model__")
        if model_label:
            model = apps.get_model(model_label)
            if model is None:
                return None
            return model.objects.filter(pk=value.get("pk")).first()

        model_class_label = value.get("__model_class__")
        if model_class_label:
            return apps.get_model(model_class_label)

        return {
            key: deserialize_workflow_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [deserialize_workflow_value(item) for item in value]
    return value
