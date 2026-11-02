"""Reuse the signing component for a recipient-scoped email invitation."""

from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from bloomerp.components.document_signing.sign_document import SignDocumentComponent
from bloomerp.document_signing.access import get_invited_recipient
from bloomerp.models.document_signing import SignatureRecipient
from bloomerp.router import router


@router.register(
    path="components/document_signing/invitation/<str:recipient_id>",
    url_name="components_document_signing_invitation",
)
@method_decorator(never_cache, name="dispatch")
class InvitationSigningComponent(SignDocumentComponent):
    """Delegate only the emailed recipient's fields without granting general model access."""

    signing_route = "components_document_signing_invitation"
    pdf_route = "components_document_signing_invitation_pdf"

    def invitation_token(self, recipient_id: str) -> str:
        """Carry the signed capability through rendering and completion."""
        return recipient_id

    def resolve_recipient(
        self, request: HttpRequest, recipient_id: str
    ) -> SignatureRecipient:
        """Validate the invitation independently of any unrelated logged-in browser account."""
        return get_invited_recipient(recipient_id)
