"""Authenticated, CSRF-protected message submission from the shared text editor."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.router import router


@router.register(
    path="components/communication/conversation/<uuid:conversation_id>/send/",
    url_name="components_im_send_message",
)
@login_required
@require_POST
def send_message(request: HttpRequest, conversation_id: UUID) -> JsonResponse:
    """Validate a send through the controller and acknowledge its stable message ID."""
    try:
        message = IMController(request.user).send_message(
            conversation_id,
            request.POST.get("body_html", ""),
            request.POST.get("client_id", ""),
            reply_to_id=request.POST.get("reply_to") or None,
            thread_root_id=request.POST.get("thread_root") or None,
        )
    except (ValidationError, ValueError) as error:
        return JsonResponse(
            {
                "error": "; ".join(error.messages)
                if isinstance(error, ValidationError)
                else "Invalid message reference."
            },
            status=400,
        )
    return JsonResponse(
        {"message_id": str(message.pk)}, headers={"Cache-Control": "private, no-store"}
    )
