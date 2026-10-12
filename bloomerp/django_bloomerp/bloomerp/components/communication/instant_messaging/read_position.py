"""Acknowledge rendered conversation messages without mutating on GET requests."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.router import router


@router.register(
    path="components/communication/conversation/<uuid:conversation_id>/read/",
    url_name="components_im_read_position",
)
@login_required
@require_POST
def read_position(request: HttpRequest, conversation_id: UUID) -> JsonResponse:
    """Advance an authorized viewer's monotonic read marker for the displayed timeline."""
    try:
        from django.core import signing
        from django.db import transaction
        from django.shortcuts import get_object_or_404
        from django.utils.dateparse import parse_datetime
        from bloomerp.communication.builtins.instant_messaging.access import (
            IMAccessManager,
        )
        from bloomerp.communication.builtins.instant_messaging.inbox_source import (
            sync_conversation_read,
        )

        if request.POST.get("activity_token"):
            payload = signing.loads(
                request.POST["activity_token"], salt="im-activity-read", max_age=3600
            )
            if payload["conversation"] != str(conversation_id) or request.POST.get(
                "thread_root"
            ):
                raise ValueError
            timestamp = parse_datetime(payload["at"])
            if timestamp is None:
                raise ValueError
            with transaction.atomic():
                chat = get_object_or_404(
                    IMAccessManager(request.user).get_conversations(),
                    pk=conversation_id,
                )
                member = chat.participants.select_for_update().get(
                    user=request.user, left_at__isnull=True
                )
                if (
                    member.last_read_activity_at is None
                    or member.last_read_activity_at < timestamp
                ):
                    member.last_read_activity_at = timestamp
                    member.save(update_fields=["last_read_activity_at"])
            sync_conversation_read(conversation_id, request.user.pk)
        if request.POST.get("message_id"):
            message_id = UUID(request.POST["message_id"])
            thread_id = (
                UUID(request.POST["thread_root"])
                if request.POST.get("thread_root")
                else None
            )
            IMController(request.user).mark_read(conversation_id, message_id, thread_id)
        elif not request.POST.get("activity_token"):
            raise ValueError
    except (ValueError, ValidationError, signing.BadSignature, KeyError):
        return JsonResponse({"error": "Invalid read position."}, status=400)
    return JsonResponse({"ok": True}, headers={"Cache-Control": "private, no-store"})
