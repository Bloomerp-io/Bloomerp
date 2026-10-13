"""Set the requester's emoji reaction through the messaging controller."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.router import router


@router.register(
    path="components/communication/conversation/<uuid:conversation_id>/message/<uuid:message_id>/reaction/",
    url_name="components_im_reaction",
)
@login_required
@require_POST
def reaction(
    request: HttpRequest, conversation_id: UUID, message_id: UUID
) -> JsonResponse:
    """Apply an explicit desired state so network retries never toggle twice."""
    try:
        if request.POST.get("active") not in ("true", "false"):
            raise ValidationError("A reaction state is required.")
        IMController(request.user).set_reaction(
            conversation_id,
            message_id,
            request.POST.get("emoji", ""),
            request.POST["active"] == "true",
        )
    except ValidationError as error:
        return JsonResponse({"error": "; ".join(error.messages)}, status=400)
    return JsonResponse({"ok": True}, headers={"Cache-Control": "private, no-store"})
