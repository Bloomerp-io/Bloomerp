"""Output-port definitions for extensible workflow nodes."""

from dataclasses import dataclass
import re


DEFAULT_PORT_ID = "default"
_PORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class WorkflowNodeOutputPort:
    """A named output connection exposed by a workflow node.

    ``max_connections=None`` allows an unlimited number of edges. Executors
    that declare no ports receive one implicit, unlimited ``default`` port.
    """

    id: str
    label: str
    max_connections: int | None = 1

    def __post_init__(self) -> None:
        if not self.id or not _PORT_ID_PATTERN.fullmatch(self.id):
            raise ValueError(
                "Workflow output port IDs may contain letters, numbers, "
                "underscores, and hyphens."
            )
        if self.max_connections is not None and self.max_connections < 1:
            raise ValueError("max_connections must be positive or None.")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "max_connections": self.max_connections,
        }


DEFAULT_OUTPUT_PORT = WorkflowNodeOutputPort(
    id=DEFAULT_PORT_ID,
    label="Output",
    max_connections=None,
)


def validate_output_ports(
    ports: list[WorkflowNodeOutputPort] | tuple[WorkflowNodeOutputPort, ...],
) -> tuple[WorkflowNodeOutputPort, ...]:
    normalized = tuple(ports)
    port_ids = [port.id for port in normalized]
    if len(port_ids) != len(set(port_ids)):
        raise ValueError("Workflow output port IDs must be unique per node.")
    return normalized
