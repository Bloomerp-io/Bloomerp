"""Public landing page for an explicitly delegated email signing invitation."""

from typing import Any
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET
from rest_framework.exceptions import APIException

from bloomerp.document_signing.access import get_invited_recipient
from bloomerp.models.document_signing import SignatureRequest
from bloomerp.router import router


@router.register(
    path="sign/<str:token>/",
    route_type="detail",
    models=[SignatureRequest],
    url_name="invitation",
    name="Signing invitation",
)
@require_GET
@never_cache
@ensure_csrf_cookie
def invitation(
    request: HttpRequest, pk: UUID, token: str, **kwargs: Any
) -> HttpResponse:
    """Open the emailed signer only when its token belongs to the request in the URL."""
    context: dict[str, object] = {}
    status = 200
    try:
        get_invited_recipient(token, request_id=pk)
        context["signing_url"] = reverse(
            "components_document_signing_invitation", kwargs={"recipient_id": token}
        )
    except APIException as error:
        context["error"] = str(error.detail)
        status = error.status_code
    response = render(
        request, "document_signing/invitation.html", context, status=status
    )
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
