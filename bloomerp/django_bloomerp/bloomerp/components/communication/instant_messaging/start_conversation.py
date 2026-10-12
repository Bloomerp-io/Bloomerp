"""Start a native conversation from a revalidated recipient selection."""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.router import router

from .conversation import render_conversation


@router.register(
    path="components/communication/im/start/",
    url_name="components_im_start_conversation",
)
@login_required
@require_POST
def start_conversation(request: HttpRequest) -> HttpResponse:
    """Create or reuse an internal direct chat and return its reusable fragment."""
    recipient_id = request.POST.get("recipient_id", "")
    if not recipient_id:
        return HttpResponse(status=400)
    try:
        chat = IMController(request.user).start_internal_conversation(recipient_id)
    except (ValueError, ValidationError):
        return HttpResponse(status=400)
    response = render_conversation(request, chat.pk)
    response["HX-Trigger"] = json.dumps(
        {"im:conversation-opened": {"id": str(chat.pk)}}
    )
    return response
