"""Stream a signing PDF only through its recipient's signed email capability."""

from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from bloomerp.components.document_signing.signing_pdf import SigningPdfComponent
from bloomerp.document_signing.access import get_invited_recipient
from bloomerp.models.document_signing import SignatureRecipient
from bloomerp.router import router


@router.register(
    path="components/document_signing/invitation_pdf/<str:recipient_id>",
    url_name="components_document_signing_invitation_pdf",
)
@method_decorator(never_cache, name="dispatch")
class InvitationPdfComponent(SigningPdfComponent):
    """Keep the original and completed PDF behind the same invitation as the signing form."""

    def resolve_recipient(
        self, request: HttpRequest, recipient_id: str
    ) -> SignatureRecipient:
        """Resolve one recipient's non-expired request from the signed link."""
        return get_invited_recipient(recipient_id)
