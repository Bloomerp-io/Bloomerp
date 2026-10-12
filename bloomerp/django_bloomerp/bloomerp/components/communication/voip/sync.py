"""Compatibility endpoint for the connection synchronization object action."""

from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from bloomerp.router import router
from bloomerp.models.communication.voip import VoIPConnection
from bloomerp.communication.builtins.voip.actions import synchronize_numbers


@router.register(
    path="components/communication/voip/<uuid:connection_id>/sync/",
    url_name="components_voip_sync",
)
@login_required
@require_POST
def sync_connection(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    """Delegate legacy synchronization requests to the permission-checked object action."""
    return synchronize_numbers(
        request, get_object_or_404(VoIPConnection, pk=connection_id)
    )
