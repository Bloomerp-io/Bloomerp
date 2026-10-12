"""Owner-authorized connection validation and synchronization."""

from uuid import UUID
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _
from twilio.base.exceptions import TwilioException
from requests.exceptions import RequestException
from bloomerp.router import router
from bloomerp.communication.builtins.voip.controller import VoIPController, callback_url


@router.register(
    path="components/communication/voip/<uuid:connection_id>/sync/",
    url_name="components_voip_sync",
)
@login_required
@require_POST
def sync_connection(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    """Validate remote access and render imported numbers with exact callback URLs."""
    try:
        connection = VoIPController(request.user).synchronize(connection_id)
    except (ValidationError, ValueError, TwilioException, RequestException):
        return HttpResponse(
            _(
                "Synchronization failed. Check the account credentials and provider configuration."
            ),
            status=400,
        )
    return render(
        request,
        "components/communication/voip/connection.html",
        {
            "connection": connection,
            "numbers": connection.numbers.prefetch_related("assigned_users"),
            "staff": get_user_model().objects.filter(is_staff=True, is_active=True),
            "voice_url": callback_url(connection, "voice"),
            "sms_url": callback_url(connection, "sms"),
            "status_url": callback_url(connection, "call_status"),
        },
    )
