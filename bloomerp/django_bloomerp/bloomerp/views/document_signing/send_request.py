"""Email the existing assignments of a saved signature request."""

from typing import Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import APIException

from bloomerp.components.document_signing.send_signature_request import (
    render_signature_composer,
)
from bloomerp.document_signing.access import (
    can_assign_signing_request,
    can_send_signing_request,
    can_share_signing_request,
    get_signing_preparation,
)
from bloomerp.document_signing.preparation import preparation_payload
from bloomerp.models.document_signing import SignatureRequest
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="send/",
    route_type="detail",
    models=[SignatureRequest],
    url_name="send",
    name="Send signature request",
)
@transaction.non_atomic_requests
@login_required
@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def send_request(request: HttpRequest, pk: UUID, **kwargs: Any) -> HttpResponse:
    """Assign a saved draft's recipients or email existing assignments using the shared composer."""
    return compose_signature_request(request, pk)


def compose_signature_request(
    request: HttpRequest, pk: UUID, *, assign_only: bool = False
) -> HttpResponse:
    """Render and process the shared role composer for assignment or invitation delivery."""
    manager = UserPolicyManager(request.user)
    signing_request = get_object_or_404(
        manager.get_accessible_queryset(SignatureRequest, "view").select_related(
            "original_file", "email_account"
        ),
        pk=pk,
    )
    assigning = (
        assign_only
        or signing_request.status == "draft"
        or (request.method == "POST" and "submission_id" in request.POST)
    )
    if assign_only:
        allowed = can_assign_signing_request(signing_request, manager) or (
            request.method == "POST"
            and can_share_signing_request(signing_request, manager)
        )
    else:
        allowed = can_send_signing_request(
            signing_request, manager
        ) or can_share_signing_request(signing_request, manager)
    if not allowed:
        raise PermissionDenied("You cannot distribute this signing request.")
    source = None
    if assigning:
        try:
            source = get_signing_preparation(
                manager,
                str(signing_request.original_file_id),
                signing_request.source_preparation_id,
            )
            preparation_payload(source, manager)
        except APIException as error:
            return HttpResponse(str(error.detail), status=error.status_code)
    return render_signature_composer(
        request,
        manager,
        file=signing_request.original_file,
        source=source,
        signing_request=signing_request,
        assign_only=assign_only,
        reload_on_complete=True,
        send_url=reverse(
            "signature_requests_detail_assign"
            if assign_only
            else "signature_requests_detail_send",
            kwargs={"pk": pk},
        ),
    )
