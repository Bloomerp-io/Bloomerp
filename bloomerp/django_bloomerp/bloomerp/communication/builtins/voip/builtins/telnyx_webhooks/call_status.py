"""Normalize Telnyx TeXML status events into existing carrier history."""

from dataclasses import replace

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from bloomerp.communication.builtins.voip.controller import reconcile_call
from bloomerp.communication.builtins.voip.definition import VoIPCallData
from bloomerp.models.communication.voip import PhoneCall, VoIPConnection


def call_status(request: HttpRequest, connection: VoIPConnection) -> HttpResponse:
    """Reconcile known call legs idempotently without turning SIP addresses into chat contacts."""
    data = request.POST
    status = data.get("DialCallStatus") or data.get("CallStatus", "")
    status = {"initiated": "queued", "answered": "in-progress"}.get(status, status)
    if status not in {
        value for value, _label in PhoneCall._meta.get_field("status").choices
    } or not data.get("CallSid"):
        return HttpResponse(status=400)
    parent_id = data.get("ParentCallSid", "")
    call = PhoneCall.objects.filter(
        connection=connection, provider_call_id=data["CallSid"]
    ).first()
    parent = (
        PhoneCall.objects.filter(
            connection=connection, provider_call_id=parent_id
        ).first()
        if parent_id
        else None
    )
    source = call or parent
    if source is None:
        # A progress callback can beat the Voice request; ask Telnyx to retry.
        return HttpResponse(status=503)
    try:
        duration = max(
            0, int(data.get("DialCallDuration") or data.get("CallDuration") or 0)
        )
        ended = parse_datetime(data.get("EndTime", ""))
    except ValueError:
        return HttpResponse(status=400)
    terminal = status in {"completed", "busy", "no-answer", "canceled", "failed"}
    remote = VoIPCallData(
        data["CallSid"],
        parent_id,
        source.from_address,
        source.to_address,
        source.direction,
        status,
        None,
        (ended or timezone.now()) if terminal else None,
        duration,
    )
    event_id = (
        f"telnyx:{remote.external_id}:{data.get('SequenceNumber', status)}:{status}"
    )
    reconcile_call(connection, remote, event_id)
    # A failed parallel child must not end the parent while another staff member answers.
    # The Dial action callback supplies the aggregate terminal outcome on the root.
    if parent and status == "in-progress":
        reconcile_call(
            connection,
            replace(
                remote,
                external_id=parent.provider_call_id,
                parent_id="",
                from_address=parent.from_address,
                to_address=parent.to_address,
                direction=parent.direction,
            ),
            f"child:{event_id}",
        )
    return HttpResponse("<Response/>", content_type="application/xml")
