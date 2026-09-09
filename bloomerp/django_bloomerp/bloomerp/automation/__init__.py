"""Stable public API for implementing BloomERP workflow nodes."""

from bloomerp.automation.base_executor import BaseExecutor, NodeExecutionError
from bloomerp.automation.ports import WorkflowNodeOutputPort
from bloomerp.automation.registry import (
    WORKFLOW_NODE_REGISTRY,
    WorkflowNodeDefinition,
)
from bloomerp.automation.results import (
    DeferResult,
    FanOutResult,
    PauseResult,
    PreparedInput,
    RouteResult,
    StopBranchResult,
)
from bloomerp.automation.runtime import WorkflowNodeExecutionContext
from bloomerp.automation.schema import (
    WorkflowIOFlowKind,
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    WorkflowValueType,
)


__all__ = [
    "BaseExecutor",
    "DeferResult",
    "FanOutResult",
    "NodeExecutionError",
    "PauseResult",
    "PreparedInput",
    "RouteResult",
    "StopBranchResult",
    "WORKFLOW_NODE_REGISTRY",
    "WorkflowIOFlowKind",
    "WorkflowIOSchema",
    "WorkflowInputRequirement",
    "WorkflowNodeDefinition",
    "WorkflowNodeExecutionContext",
    "WorkflowNodeOutputPort",
    "WorkflowValueField",
    "WorkflowValueType",
]
