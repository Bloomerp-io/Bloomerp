"""Idempotent carrier call-state reconciliation."""

from uuid import UUID
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from bloomerp.router import router
from bloomerp.communication.builtins.voip.webhooks import verified_connection
from bloomerp.communication.builtins.voip.controller import reconcile_call
from bloomerp.communication.builtins.voip.definition import VoIPCallData
from bloomerp.models.communication.voip import PhoneCall


@router.register(
    path="communication/voip/<uuid:connection_id>/call-status/",
    url_name="voip_call_status",
)
@csrf_exempt
@require_POST
def call_status(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    """Retain each leg while projecting a child outcome onto its outgoing call card."""
    connection = verified_connection(request, connection_id, "call_status")
    data = request.POST
    status = data.get("DialCallStatus") or data.get("CallStatus", "")
    if status not in {
        value for value, label in PhoneCall._meta.get_field("status").choices
    } or not data.get("CallSid"):
        return HttpResponse(status=400)
    try:
        duration = max(
            0, int(data.get("DialCallDuration") or data.get("CallDuration", "0"))
        )
    except ValueError:
        return HttpResponse(status=400)
    remote = VoIPCallData(
        data["CallSid"],
        data.get("ParentCallSid", ""),
        data.get("From", ""),
        data.get("To", ""),
        "inbound" if data.get("Direction") == "inbound" else "outbound",
        status,
        None,
        timezone.now()
        if status in {"completed", "busy", "no-answer", "canceled", "failed"}
        else None,
        duration,
    )
    event_id = f"{remote.external_id}:{data.get('SequenceNumber', status)}"
    reconcile_call(connection, remote, event_id)
    if remote.parent_id:
        parent = PhoneCall.objects.filter(
            connection=connection,
            provider_call_id=remote.parent_id,
            direction="outbound",
        ).first()
        if parent:
            reconcile_call(
                connection,
                VoIPCallData(
                    parent.provider_call_id,
                    "",
                    parent.from_address,
                    parent.to_address,
                    parent.direction,
                    status,
                    None,
                    remote.ended_at,
                    duration,
                ),
                f"child:{event_id}",
            )
    return (
        HttpResponse("<Response/>", content_type="application/xml")
        if data.get("DialCallStatus")
        else HttpResponse(status=204)
    )
