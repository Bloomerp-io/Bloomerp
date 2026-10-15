"""Public model view for a single shared meeting, with no conversation access."""

from typing import Any
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from bloomerp.communication.builtins.conferencing.sharing import (
    account_presentation,
    shared_session,
)
from bloomerp.models.communication.conferencing import ConferenceSession
from bloomerp.router import router


@router.register(
    path="meeting/<uuid:token>/",
    route_type="model",
    models=ConferenceSession,
    url_name="meeting",
    name="Join meeting",
    searchable=False,
)
@never_cache
@require_GET
def meeting(
    request: HttpRequest, token: UUID, model: type[ConferenceSession], **kwargs: Any
) -> HttpResponse:
    """Show account identity or a guest name form before browser-bound admission."""
    session = shared_session(token)
    response = render(
        request,
        "views/communication/conferencing/meeting.html",
        {
            "token": token,
            "joining_name": account_presentation(request.user, session)["displayName"]
            if request.user.is_authenticated
            else "",
        },
    )
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
