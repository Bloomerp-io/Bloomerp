"""Respond to a scheduling invitation from a secured inbox email screen."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from bloomerp.communication.calendar.access import invitation_context
from bloomerp.communication.calendar.outgoing import respond_to_calendar_invitation
from bloomerp.communication.utils.permissions import accessible_inbox_items
from bloomerp.router import router


@router.register(
    path="components/communication/calendar/respond/<uuid:item_id>/",
    url_name="components_calendar_respond",
)
@login_required
@require_POST
def respond(request: HttpRequest, item_id: UUID) -> HttpResponse:
    """Check Inbox access and independent calendar policies before sending a response."""
    item = get_object_or_404(
        accessible_inbox_items(request.user).filter(item_type="email"), pk=item_id
    )
    context = invitation_context(item, request.user)
    if context is None:
        return HttpResponse("This calendar invitation is not available.", status=403)
    try:
        expected_sequence = int(request.POST["sequence"])
        respond_to_calendar_invitation(
            user=request.user,
            event_id=context["event"].pk,
            email_account_id=UUID(item.folder.related_object_id),
            inbox_id=item.folder.inbox.effective_preference.pk,
            response_status=request.POST.get("response_status", ""),
            expected_sequence=expected_sequence,
        )
    except (ValueError, KeyError, ValidationError) as exc:
        error = (
            "; ".join(exc.messages)
            if isinstance(exc, ValidationError)
            else "Invalid calendar response."
        )
        return render(
            request,
            "components/communication/calendar/invitation.html",
            {
                "calendar_invitation": invitation_context(item, request.user),
                "calendar_error": error,
            },
            status=400,
        )
    return render(
        request,
        "components/communication/calendar/invitation.html",
        {"calendar_invitation": invitation_context(item, request.user)},
    )
