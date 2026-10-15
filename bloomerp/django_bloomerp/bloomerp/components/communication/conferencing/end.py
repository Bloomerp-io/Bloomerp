"""Host-authorized conference termination."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.controller import (
    ConferenceController,
    ConferenceUnavailable,
    session_payload,
)
from bloomerp.router import router


@router.register(
    path="components/communication/conferencing/<uuid:session_id>/end/",
    url_name="components_conferencing_end",
)
@login_required
@require_POST
def end(request: HttpRequest, session_id: UUID) -> JsonResponse:
    """Close the session before media cleanup; retries complete uncertain deletion."""
    headers = {"Cache-Control": "private, no-store"}
    try:
        session = ConferenceController(request.user).end(session_id)
    except (ConferenceUnavailable, ImproperlyConfigured):
        return JsonResponse(
            {"error": _("The call is closed locally. Retry to confirm media cleanup.")},
            status=503,
            headers=headers,
        )
    return JsonResponse(session_payload(session), headers=headers)
