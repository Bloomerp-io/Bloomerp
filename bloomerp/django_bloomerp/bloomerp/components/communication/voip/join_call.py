"""Authorize one outgoing phone call for the common browser calling controller."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.voip.im_calling import join
from bloomerp.router import router


@router.register(
    path="components/communication/voip/calls/<uuid:call_id>/join/",
    url_name="components_voip_join_call",
)
@login_required
@require_POST
def join_call(request: HttpRequest, call_id: UUID) -> JsonResponse:
    """Return scoped carrier credentials after current line and reservation checks."""
    try:
        data = join(request.user, call_id)
    except ValidationError:
        return JsonResponse(
            {"error": "This phone call is no longer available."}, status=400
        )
    return JsonResponse(data, headers={"Cache-Control": "private, no-store"})
