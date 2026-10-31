"""Compose recipients for a PDF using a reusable layout or a document preparation."""

from typing import Any
from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import APIException

from bloomerp.document_signing.access import can_prepare, can_signing_access
from bloomerp.document_signing.requests import (
    create_signature_request,
    send_signature_emails,
    signing_evidence,
)
from bloomerp.forms.document_signing.send_signature_request import (
    SendSignatureRequestForm,
    SignatureDispatchForm,
    SignatureRequestEmailForm,
)
from bloomerp.models.document_signing import (
    SignatureLayout,
    SignaturePreparation,
    SignatureRequest,
)
from bloomerp.models.files.file_node import FileNode
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/document_signing/send_signature_request/<str:file_id>",
    url_name="components_document_signing_send_signature_request",
)
@transaction.non_atomic_requests
@login_required
@require_http_methods(["GET", "POST"])
@ensure_csrf_cookie
def send_signature_request(request: HttpRequest, file_id: str) -> HttpResponse:
    """Render the composer or dispatch one immutable request for every selected signer."""
    data = request.POST if request.method == "POST" else request.GET
    layout_id = data.get("layout_id")
    preparation_id = data.get("preparation_id")
    if bool(layout_id) == bool(preparation_id):
        return HttpResponseBadRequest("Choose one signing layout or preparation.")

    manager = UserPolicyManager(request.user)
    try:
        file = get_object_or_404(FileNode, pk=file_id, kind="FILE")
        if not can_prepare(file, manager):
            raise PermissionDenied
        if file.metadata.extension != "pdf":
            return HttpResponseBadRequest("Choose a PDF document.")
        if preparation_id:
            source = get_object_or_404(
                manager.get_accessible_queryset(
                    SignaturePreparation, BloomerpPermission.VIEW
                ),
                pk=preparation_id,
                original_file=file,
            )
            source_fields = ["title", "revision", "original_file"]
            role_fields = ["preparation", "key", "label", "signing_order"]
        else:
            source = get_object_or_404(
                manager.get_accessible_queryset(
                    SignatureLayout, BloomerpPermission.VIEW
                ),
                pk=layout_id,
            )
            source_fields = ["name", "revision"]
            role_fields = ["layout", "key", "label", "default_signing_order"]
    except (ValidationError, ValueError) as error:
        raise Http404("Invalid signing document or layout.") from error

    if not can_signing_access(
        source, manager, BloomerpPermission.VIEW, tuple(source_fields)
    ):
        raise PermissionDenied
    roles = list(source.roles.all())
    if not roles:
        return HttpResponseBadRequest("Add at least one signer role before sending.")
    for role in roles:
        if not can_signing_access(
            role, manager, BloomerpPermission.VIEW, tuple(role_fields)
        ):
            raise PermissionDenied

    try:
        submission_id = (
            UUID(request.GET["submission_id"])
            if "submission_id" in request.GET
            else uuid4()
        )
    except ValueError:
        return HttpResponseBadRequest("Choose a valid submission identifier.")
    return render_signature_composer(
        request,
        manager,
        file=file,
        source=source,
        submission_id=submission_id,
        send_url=reverse(
            "components_document_signing_send_signature_request",
            kwargs={"file_id": file.pk},
        ),
    )


def render_signature_composer(
    request: HttpRequest,
    manager: UserPolicyManager,
    *,
    file: FileNode,
    send_url: str,
    source: SignatureLayout | SignaturePreparation | None = None,
    signing_request: SignatureRequest | None = None,
    submission_id: UUID | None = None,
    assign_only: bool = False,
    reload_on_complete: bool = False,
) -> HttpResponse:
    """Compose, validate and submit new requests or saved assignments through one form contract."""
    component_id = f"send-signature-request-{uuid4().hex}"
    form_options: dict[str, Any] = {
        "user": request.user,
        "data": request.POST if request.method == "POST" else None,
        "auto_id": f"id_{component_id}_%s",
    }
    if signing_request is not None:
        form_options["initial"] = {
            "sender": signing_request.email_account_id,
            "content": signing_request.email_content,
            "valid_until": signing_request.expires_at,
        }
    dispatch_form = None
    if source is not None:
        form = SendSignatureRequestForm(
            roles=list(source.roles.all()), assign_only=assign_only, **form_options
        )
        dispatch_form = SignatureDispatchForm(
            data=request.POST if request.method == "POST" else None,
            initial={
                "submission_id": submission_id or uuid4(),
                "source_revision": signing_request.source_preparation_revision
                if signing_request
                else source.revision,
            },
            auto_id=f"id_{component_id}_dispatch_%s",
        )
    else:
        form = SignatureRequestEmailForm(**form_options)
    if request.method == "POST":
        valid_form = form.is_valid()
        valid_dispatch = dispatch_form is None or dispatch_form.is_valid()
        if not valid_form or not valid_dispatch:
            return JsonResponse(
                {
                    "errors": {
                        **dict(form.errors),
                        **dict(dispatch_form.errors if dispatch_form else {}),
                    }
                },
                status=400,
            )
        try:
            if source is not None:
                sender = (
                    signing_request.email_account
                    if assign_only and signing_request
                    else (
                        form.cleaned_data["sender"]
                        if form.cleaned_data["send_email"]
                        else None
                    )
                )
                signing_request = create_signature_request(
                    manager,
                    file,
                    source,
                    dispatch_form.cleaned_data["source_revision"],
                    dispatch_form.cleaned_data["submission_id"],
                    form.assignments,
                    sender,
                    signing_request.email_content
                    if assign_only and signing_request
                    else form.cleaned_data["content"],
                    signing_request.expires_at
                    if assign_only and signing_request
                    else form.cleaned_data["valid_until"],
                    signing_evidence(request.META),
                    request_id=signing_request.pk if signing_request else None,
                    assign_only=assign_only,
                )
            if assign_only:
                return JsonResponse(
                    {"status": "assigned", "request_id": str(signing_request.pk)}
                )
            result = send_signature_emails(
                manager,
                signing_request,
                request.build_absolute_uri("/"),
                **(
                    {}
                    if source is not None
                    else {
                        "sender": form.cleaned_data["sender"],
                        "content": form.cleaned_data["content"],
                    }
                ),
            )
        except ValidationError as error:
            return JsonResponse({"errors": error.messages}, status=400)
        except APIException as error:
            return JsonResponse({"errors": error.detail}, status=error.status_code)
        return JsonResponse(
            result, status=202 if result["status"] == "unconfirmed" else 200
        )
    return render(
        request,
        "components/document_signing/send_signature_request.html",
        {
            "component_id": component_id,
            "file": file,
            "layout_id": str(source.pk)
            if isinstance(source, SignatureLayout)
            else None,
            "preparation_id": str(source.pk)
            if isinstance(source, SignaturePreparation)
            else None,
            "source_revision": source.revision if source else None,
            "existing_request": signing_request if source is None else None,
            "existing_recipients": signing_request.recipients.filter(
                status__in=["pending", "viewed"]
            )
            if signing_request is not None and source is None
            else [],
            "form": form,
            "dispatch_form": dispatch_form,
            "assign_only": assign_only,
            "reload_on_complete": reload_on_complete,
            "send_url": send_url,
        },
    )
