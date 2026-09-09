"""Runtime context passed to advanced workflow-node preparation hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from bloomerp.automation.workflow_state import ScopeKey, WorkflowRunState

if TYPE_CHECKING:
    from bloomerp.models.automation.workflow_node import WorkflowNode
    from bloomerp.models.automation.workflow_run import WorkflowRun
    from bloomerp.models.automation.workflow_run_step import WorkflowRunStep


RuntimeOutputKey = tuple[str, int, ScopeKey, int]


@dataclass
class WorkflowNodeExecutionContext:
    """State available to an executor's advanced ``prepare`` hook."""

    node: WorkflowNode
    workflow_run: WorkflowRun
    state: WorkflowRunState
    from_node: WorkflowNode | None
    from_step: WorkflowRunStep | None
    scope_key: ScopeKey
    transient_outputs: dict[RuntimeOutputKey, Any] = field(default_factory=dict)
    load_step_output: Callable[[WorkflowRunStep], Any] | None = None

    def set_transient_output(
        self,
        namespace: str,
        scope_key: ScopeKey,
        source_id: int,
        output: Any,
    ) -> None:
        self.transient_outputs[(namespace, self.node.id, scope_key, source_id)] = output

    def get_transient_output(
        self,
        namespace: str,
        scope_key: ScopeKey,
        source_id: int,
    ) -> tuple[bool, Any]:
        key = (namespace, self.node.id, scope_key, source_id)
        if key not in self.transient_outputs:
            return False, None
        return True, self.transient_outputs[key]

    def scope_ancestors(self) -> list[ScopeKey]:
        return [
            self.scope_key[:length]
            for length in range(len(self.scope_key), -1, -1)
        ]
