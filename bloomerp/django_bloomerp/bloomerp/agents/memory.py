"""Persist and assemble conversation memory without knowing endpoint payload shapes."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from bloomerp.mcp.memory import McpMemoryPolicy

if TYPE_CHECKING:
    from bloomerp.models.agents import AIConversation, AIToolCall

MAX_CONTEXT_CHARS = 12000
MAX_MEMORY_RECORDS = 100
MAX_RECORD_CHARS = 12000


def memory_policies() -> dict[str, McpMemoryPolicy]:
    """Resolve optional local endpoint policies using registered tool identities."""
    from bloomerp.router import router

    return {
        route.url_name: route.mcp.memory
        for route in router.get_mcp_routes()
        if getattr(route.mcp, "memory", None) is not None
    }


def read_only_memory_tools() -> set[str]:
    """Identify local memory producers explicitly registered as read-only tools."""
    from bloomerp.router import router

    return {
        route.url_name
        for route in router.get_mcp_routes()
        if getattr(route.mcp, "memory", None) is not None
        and getattr(route.mcp, "read_only_hint", None) is True
    }


def remember_tool_result(tool: AIToolCall) -> None:
    """Idempotently merge successful tool facts, serializing writers per conversation."""
    from bloomerp.models.agents import AIConversation, AIConversationMemory

    policy = memory_policies().get(tool.tool_identifier)
    if (
        policy is None
        or tool.status != "completed"
        or not isinstance(tool.result, dict)
    ):
        return
    if tool.result.get("isError"):
        return
    facts = policy.extract(tool.result)
    with transaction.atomic():
        conversation = AIConversation.objects.select_for_update().get(
            pk=tool.run.conversation_id
        )
        if tool.run.initiated_by_id != conversation.owner_id:
            return
        for key, payload in list(facts.items())[:MAX_MEMORY_RECORDS]:
            if not isinstance(key, str) or len(key) > 255:
                continue
            memory = (
                AIConversationMemory.objects.filter(
                    conversation=conversation,
                    tool_identifier=tool.tool_identifier,
                    key=key,
                )
                .select_related("source_tool_call")
                .first()
            )
            if memory is not None:
                if memory.source_tool_call_id == tool.pk:
                    continue
                if memory.source_tool_call.datetime_created > tool.datetime_created:
                    continue
                if memory.version == policy.version and (
                    memory.expires_at is None or memory.expires_at > timezone.now()
                ):
                    payload = policy.merge(memory.payload, payload)
            if len(json.dumps(payload, ensure_ascii=False)) > MAX_RECORD_CHARS:
                continue
            if memory is None:
                memory = AIConversationMemory(
                    conversation=conversation,
                    tool_identifier=tool.tool_identifier,
                    key=key,
                )
            memory.payload = payload
            memory.version = policy.version
            memory.source_tool_call = tool
            memory.expires_at = timezone.now() + policy.ttl if policy.ttl else None
            memory.save()


def conversation_memory_context(
    conversation: AIConversation, *, before_sequence: int
) -> str | None:
    """Reuse successful reads even after interruption, revalidating bounded notes."""
    from django.db.models import Q

    policies = memory_policies()
    records = (
        conversation.memories.filter(
            source_tool_call__status="completed",
            source_tool_call__run__trigger_message__sequence__lt=before_sequence,
            source_tool_call__run__initiated_by=conversation.owner,
        )
        .filter(
            Q(source_tool_call__run__status="completed")
            | Q(tool_identifier__in=read_only_memory_tools())
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("-source_tool_call__datetime_created", "key")[:MAX_MEMORY_RECORDS]
    )
    grouped: dict[str, dict[str, dict]] = {}
    for record in records:
        policy = policies.get(record.tool_identifier)
        if policy is not None and record.version == policy.version:
            grouped.setdefault(record.tool_identifier, {})[record.key] = record.payload
    request = HttpRequest()
    request.user = conversation.owner
    sections: list[str] = []
    remaining = MAX_CONTEXT_CHARS
    for identifier, facts in grouped.items():
        policy = policies[identifier]
        try:
            validated = policy.validate(request, facts)
        except Exception:
            logging.getLogger(__name__).exception(
                "Memory validation failed for %s", identifier
            )
            continue  # Never inject unchecked notes or fail the user's request.
        entries: list[str] = []
        size = len(policy.context_prefix) + 2
        for key, payload in validated.items():
            if key not in facts:
                continue
            entry = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if size + len(entry) + 1 > remaining:
                continue
            entries.append(entry)
            size += len(entry) + 1
        if entries:
            section = policy.context_prefix + "[" + ",".join(entries) + "]"
            sections.append(section)
            remaining -= len(section) + 1
    return "\n".join(sections) if sections else None
