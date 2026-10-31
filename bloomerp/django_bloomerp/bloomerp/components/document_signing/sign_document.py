"""Render and complete an existing signing request for its authenticated recipient."""

import json
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.exceptions import APIException

from bloomerp.document_signing.access import (
    REQUEST_FIELD_FIELDS,
    get_signing_recipient,
    require_signing_access,
)
from bloomerp.document_signing.requests import complete_signing, signing_evidence
from bloomerp.forms.document_signing.sign_document import SignDocumentForm
from bloomerp.models.document_signing import SignatureRecipient
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/document_signing/sign_document/<str:recipient_id>",
    url_name="components_document_signing_sign_document",
)
@method_decorator([csrf_protect, ensure_csrf_cookie], name="dispatch")
class SignDocumentComponent(View):
    """Own PDF input and consent while keeping request creation outside the signer."""

    signing_route = "components_document_signing_sign_document"
    pdf_route = "components_document_signing_signing_pdf"

    def invitation_token(self, recipient_id: str) -> str | None:
        """Keep ordinary in-app signing under the authenticated user's permissions."""
        return None

    def resolve_recipient(
        self, request: HttpRequest, recipient_id: str
    ) -> SignatureRecipient:
        """Resolve the authenticated recipient before rendering or recording any values."""
        if not request.user.is_authenticated:
            raise PermissionDenied("Sign in to open this signing request.")
        return get_signing_recipient(UserPolicyManager(request.user), recipient_id)

    def get(self, request: HttpRequest, recipient_id: str) -> HttpResponse:
        """Show immutable request fields, or the existing completion result, without writes."""
        manager = (
            UserPolicyManager(request.user)
            if self.invitation_token(recipient_id) is None
            else None
        )
        try:
            recipient = self.resolve_recipient(request, recipient_id)
            signing_request = recipient.request
            placements = list(recipient.fields.all())
            if recipient.status != "signed":
                if signing_request.status != "sent" or recipient.status not in {
                    "pending",
                    "viewed",
                }:
                    raise ValidationError("This signing request is no longer open.")
                if (
                    signing_request.expires_at
                    and signing_request.expires_at <= timezone.now()
                ):
                    raise ValidationError("This signing request has expired.")
                for field in placements:
                    if manager is not None:
                        require_signing_access(
                            field, manager, BloomerpPermission.VIEW, REQUEST_FIELD_FIELDS
                        )
        except APIException as error:
            return HttpResponse(
                str(error.detail), status=error.status_code, content_type="text/plain"
            )
        except ValidationError as error:
            return HttpResponse(
                " ".join(error.messages), status=400, content_type="text/plain"
            )
        pdf_url = reverse(
            self.pdf_route,
            kwargs={"recipient_id": recipient_id},
        )
        if recipient.status == "signed":
            return render(
                request,
                "components/document_signing/signed_document.html",
                {
                    "recipient": recipient,
                    "signing_request": signing_request,
                    "pdf_url": pdf_url,
                },
            )
        component_id = f"sign-document-{uuid4().hex}"
        form = SignDocumentForm(
            recipient=recipient, placements=placements, auto_id=f"id_{component_id}_%s"
        )
        return render(
            request,
            "components/document_signing/sign_document.html",
            {
                "component_id": component_id,
                "config_id": f"{component_id}-config",
                "form": form,
                "recipient": recipient,
                "signing_request": signing_request,
                "signing_config": {
                    "requestId": str(signing_request.pk),
                    "pdfUrl": pdf_url,
                    "submitUrl": reverse(
                        self.signing_route,
                        kwargs={"recipient_id": recipient_id},
                    ),
                    "fields": [
                        {
                            "id": str(field.pk),
                            "name": control.name,
                            "type": field.field_type,
                        }
                        for field, control in form.signing_fields
                    ],
                },
            },
        )

    def post(self, request: HttpRequest, recipient_id: str) -> JsonResponse:
        """Validate assigned values and record the signature with explicit electronic consent."""
        try:
            recipient = self.resolve_recipient(request, recipient_id)
            data = (
                json.loads(request.body)
                if request.content_type == "application/json"
                else request.POST
            )
            if not isinstance(data, dict):
                raise ValidationError("Submit the signing fields and consent.")
            invitation = self.invitation_token(recipient_id)
            result = complete_signing(
                UserPolicyManager(request.user) if invitation is None else None,
                str(recipient.pk),
                data,
                signing_evidence(request.META),
                invitation=invitation,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"errors": ["Submit valid JSON."]}, status=400)
        except ValidationError as error:
            return JsonResponse(
                {"errors": getattr(error, "message_dict", error.messages)}, status=400
            )
        except PermissionDenied as error:
            return JsonResponse({"errors": [str(error)]}, status=403)
        except APIException as error:
            return JsonResponse({"errors": error.detail}, status=error.status_code)
        return JsonResponse(
            {
                "status": result.status,
                "url": reverse(
                    self.signing_route,
                    kwargs={"recipient_id": recipient_id},
                ),
            }
        )
