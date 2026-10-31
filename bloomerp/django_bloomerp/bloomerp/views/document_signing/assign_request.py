"""Assign real recipients to a saved signature request's prepared roles."""

from typing import Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from bloomerp.models.document_signing import SignatureRequest
from bloomerp.router import router
from bloomerp.views.document_signing.send_request import compose_signature_request


@router.register(
    path="assign/",
    route_type="detail",
    models=[SignatureRequest],
    url_name="assign",
    name="Assign recipients",
)
@login_required
@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def assign_request(request: HttpRequest, pk: UUID, **kwargs: Any) -> HttpResponse:
    """Reuse the role picker to activate signing assignments without delivering invitations."""
    return compose_signature_request(request, pk, assign_only=True)
