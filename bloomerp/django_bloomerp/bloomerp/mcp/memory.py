"""Optional server-side memory policies; never serialized into MCP tool schemas."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.http import HttpRequest

MemoryPayload = dict[str, Any]
MemoryRecords = dict[str, MemoryPayload]


@dataclass(frozen=True)
class McpMemoryPolicy:
    """Let an endpoint own extraction, merging and current-access validation."""

    extract: Callable[[MemoryPayload], MemoryRecords]
    merge: Callable[[MemoryPayload, MemoryPayload], MemoryPayload]
    validate: Callable[[HttpRequest, MemoryRecords], MemoryRecords]
    context_prefix: str
    version: int = 1
    ttl: timedelta | None = None
