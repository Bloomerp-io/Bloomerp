"""Expose organizer invitation, update, and cancellation actions on event details."""

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from bloomerp.communication.calendar.access import can_schedule_event
from bloomerp.communication.calendar.outgoing import send_calendar_request
from bloomerp.models.communication.calendar import CalendarEvent
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.email_composer_services import accessible_email_accounts


@router.register(
    path="components/communication/calendar/<uuid:event_id>/schedule/",
    url_name="components_calendar_schedule",
)
@login_required
@require_http_methods(["GET", "POST"])
def schedule(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Render or execute an organizer action with account, row, and field checks."""
    manager = UserPolicyManager(request.user)
    if not manager.has_global_permission(CalendarEvent, "view"):
        raise PermissionDenied
    event = get_object_or_404(
        manager.get_accessible_queryset(CalendarEvent, "view"), pk=event_id
    )
    if not can_schedule_event(request, event):
        raise PermissionDenied
    identifiers = InboxFolder.objects.filter(
        inbox_id=event.organizing_inbox_id, type="email"
    ).values_list("related_object_id", flat=True)
    account_ids = []
    for value in identifiers:
        try:
            account_ids.append(UUID(value))
        except (ValueError, TypeError, AttributeError):
            continue
    accounts = accessible_email_accounts(request.user).filter(
        pk__in=account_ids,
        email_address__iexact=event.organizer_email,
        status="active",
    )
    context = {"calendar_event": event, "email_accounts": accounts}
    status = 200
    if request.method == "POST":
        try:
            action = request.POST.get("action", "REQUEST")
            if action not in {"REQUEST", "CANCEL"}:
                raise ValidationError("Choose invitation/update or cancellation.")
            send_calendar_request(
                user=request.user,
                event_id=event.pk,
                email_account_id=UUID(request.POST.get("email_account_id", "")),
                cancel=action == "CANCEL",
            )
            context["calendar_success"] = "Calendar email sent."
        except (ValueError, ValidationError) as exc:
            context["calendar_error"] = (
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Choose a valid email account."
            )
            status = 400
    return render(
        request,
        "components/communication/calendar/schedule.html",
        context,
        status=status,
    )
