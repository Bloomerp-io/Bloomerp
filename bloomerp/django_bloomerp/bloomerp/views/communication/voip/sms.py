"""Dispatch sms callbacks through the configured carrier definition."""

from uuid import UUID
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from bloomerp.router import router
from bloomerp.communication.builtins.voip.webhooks import dispatch_webhook


@router.register(
    path="communication/voip/<uuid:connection_id>/sms/", url_name="voip_sms"
)
@csrf_exempt
@require_POST
def sms(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    """Route the raw request to the selected provider's authenticated protocol handler."""
    return dispatch_webhook(request, connection_id, "sms")
