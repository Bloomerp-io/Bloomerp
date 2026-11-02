"""Serve original and completed signing PDFs through the recipient's access boundary."""

from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpRequest, HttpResponse
from django.views import View
from rest_framework.exceptions import APIException

from bloomerp.document_signing.access import get_signing_recipient
from bloomerp.models.document_signing import SignatureRecipient
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/document_signing/signing_pdf/<str:recipient_id>",
    url_name="components_document_signing_signing_pdf",
)
class SigningPdfComponent(View):
    """Stream PDF bytes only to the explicitly bound, currently authorized signer."""

    def resolve_recipient(
        self, request: HttpRequest, recipient_id: str
    ) -> SignatureRecipient:
        """Resolve the PDF owner through the authenticated recipient access boundary."""
        if not request.user.is_authenticated:
            raise PermissionDenied("Sign in to open this signing request.")
        return get_signing_recipient(UserPolicyManager(request.user), recipient_id)

    def get(self, request: HttpRequest, recipient_id: str) -> HttpResponse | FileResponse:
        """Return the completed PDF when available, otherwise the immutable original."""
        try:
            recipient = self.resolve_recipient(request, recipient_id)
        except APIException as error:
            return HttpResponse(
                str(error.detail), status=error.status_code, content_type="text/plain"
            )
        file = recipient.request.signed_file or recipient.request.original_file
        response = FileResponse(
            file.content.open("rb"),
            content_type="application/pdf",
            filename=file.name,
            as_attachment=request.GET.get("download") == "1",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
