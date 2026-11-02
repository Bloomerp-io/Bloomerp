"""Participant-scoped decline of an incoming conference invitation."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.controller import ConferenceController
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/<uuid:session_id>/decline/",
    url_name="components_conferencing_decline",
)
@login_required
@require_POST
def decline(request: HttpRequest, session_id: UUID) -> JsonResponse:
    """Decline only an authorized invitation and notify the actor's other tabs."""
    headers = {"Cache-Control": "private, no-store"}
    try:
        ConferenceController(request.user).decline(session_id)
    except ValidationError:
        return JsonResponse(
            {"error": _("This invitation cannot be declined.")}, status=400, headers=headers
        )
    return JsonResponse({"status": "declined"}, headers=headers)
