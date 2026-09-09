"""Public execution results understood by the workflow runtime.

Executors return ordinary Python values for normal continuation. They return
one of these result objects only when they need to influence workflow routing.
"""

from dataclasses import dataclass, field
from typing import Any

from bloomerp.automation.workflow_state import ScopeKey


@dataclass(frozen=True)
class RouteResult:
    """Send one value through a named output port."""

    port_id: str
    output: Any


@dataclass(frozen=True)
class FanOutResult:
    """Run the selected output port once for every item."""

    items: list[Any]
    port_id: str = "default"


@dataclass(frozen=True)
class StopBranchResult:
    """End the current branch without scheduling downstream nodes."""

    reason: str = "Branch stopped"


@dataclass(frozen=True)
class PauseResult:
    """Pause this workflow run until the current step is resumed."""

    output: Any


@dataclass(frozen=True)
class PreparedInput:
    """Input prepared by an executor before its normal execution."""

    input_data: Any
    scope_key: ScopeKey | None = None


@dataclass(frozen=True)
class DeferResult:
    """Defer a node until additional inputs arrive.

    This is an advanced result used by join-style nodes. Normal node
    extensions do not need to return it.
    """

    output: Any = None
    trace: bool = False
    persist_step: bool = False
    consume_sequence: bool = True
    retry_scope_keys: tuple[ScopeKey, ...] = field(default_factory=tuple)
