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
        message_id = UUID(request.POST.get("message_id", ""))
        thread_id = (
            UUID(request.POST["thread_root"])
            if request.POST.get("thread_root")
            else None
        )
        IMController(request.user).mark_read(conversation_id, message_id, thread_id)
    except (ValueError, ValidationError):
        return JsonResponse({"error": "Invalid read position."}, status=400)
    return JsonResponse({"ok": True}, headers={"Cache-Control": "private, no-store"})
