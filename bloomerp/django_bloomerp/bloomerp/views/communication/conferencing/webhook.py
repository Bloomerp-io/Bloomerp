"""Signed LiveKit webhook entrypoint independent of browser authentication."""

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.conferencing.controller import (
    ConferenceUnavailable,
)
from bloomerp.communication.builtins.conferencing.livekit import LiveKitClient
from bloomerp.communication.builtins.conferencing.webhooks import reconcile_event
from bloomerp.router import router


@router.register(
    path="communication/conferencing/webhook/", url_name="conferencing_webhook"
)
@csrf_exempt
@require_POST
def webhook(request: HttpRequest) -> HttpResponse:
    """Verify the exact raw body before any event receipt or state mutation."""
    try:
        body = request.body.decode("utf-8")
    except UnicodeDecodeError:
        return HttpResponse(status=400)
    try:
        event = LiveKitClient().verify_webhook(
            body, request.headers.get("Authorization", "")
        )
    except ImproperlyConfigured:
        return HttpResponse(status=503)
    except Exception:  # noqa: BLE001 -- LiveKit raises plain Exception for body-hash failures.
        # SDK signature/hash failures must never expose verification details.
        return HttpResponse(status=403)
    try:
        reconcile_event(event)
    except ValidationError:
        return HttpResponse(status=400)
    except ConferenceUnavailable:
        return HttpResponse(status=503)
    return HttpResponse(status=204)
