"""Disconnect an authorized email account using the registered lifecycle strategy."""

from typing import Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from bloomerp.communication.builtins.emails.authorization import disconnect_account
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.router import router


@router.register(
    path="disconnect/",
    route_type="detail",
    models=[EmailAccount],
    url_name="disconnect_email_account",
    name="Disconnect email account",
)
@login_required
@require_POST
def disconnect_email_account(request: HttpRequest, pk: UUID, **kwargs: Any) -> HttpResponse:
    """Require account change access and clear its local mailbox authorization."""
    account = get_object_or_404(EmailAccount, pk=pk)
    disconnect_account(request, account)
    response = HttpResponse(
        _("Account disconnected. Reconnect to resume receiving email.")
    )
    response["HX-Redirect"] = reverse(
        "email_accounts_detail_reconfigure_email_account", kwargs={"pk": pk}
    )
    return response
