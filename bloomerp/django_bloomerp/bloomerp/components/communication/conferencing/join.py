"""Authorize browser admission to an existing conference session."""

from uuid import UUID

from bloomerp.communication.builtins.conferencing.controller import (
    ConferenceController,
    ConferenceUnavailable,
)
from bloomerp.router import router
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST


@router.register(
    path="components/communication/conferencing/<uuid:session_id>/join/",
    url_name="components_conferencing_join",
)
@login_required
@require_POST
def join(request: HttpRequest, session_id: UUID) -> JsonResponse:
    """Return short-lived credentials only to an eligible invited participant."""
    headers = {"Cache-Control": "private, no-store"}
    try:
        payload = ConferenceController(request.user).join(session_id)
    except ValidationError:
        return JsonResponse(
            {"error": _("This call is not available to join.")},
            status=400,
            headers=headers,
        )
    except (ConferenceUnavailable, ImproperlyConfigured):
        return JsonResponse(
            {"error": _("Conferencing is unavailable.")}, status=503, headers=headers
        )
    return JsonResponse(payload, headers=headers)
