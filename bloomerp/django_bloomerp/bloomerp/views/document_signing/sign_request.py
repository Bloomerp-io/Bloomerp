"""Resolve the current user's signing assignment for a request object action."""

from typing import Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from bloomerp.components.document_signing.sign_document import SignDocumentComponent
from bloomerp.document_signing.access import get_request_signing_recipient
from bloomerp.models.document_signing import SignatureRequest
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="sign/",
    route_type="detail",
    models=[SignatureRequest],
    url_name="sign",
    name="Sign",
)
@login_required
@require_GET
def sign_request(request: HttpRequest, pk: UUID, **kwargs: Any) -> HttpResponse:
    """Open the existing signer from this request's detail route for an eligible recipient."""
    manager = UserPolicyManager(request.user)
    signing_request = get_object_or_404(
        manager.get_accessible_queryset(SignatureRequest, BloomerpPermission.VIEW),
        pk=pk,
    )
    recipient = get_request_signing_recipient(manager, signing_request)
    if recipient is None:
        raise Http404("No open signing assignment is available for this request.")
    return SignDocumentComponent.as_view()(request, recipient_id=str(recipient.pk))
