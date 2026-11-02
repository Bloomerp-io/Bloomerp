"""Domain-neutral fixtures shared by the generated signing model test cases."""

from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from typing import Any
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.utils import timezone
from pypdf import PdfWriter

from bloomerp.models.document_signing import (
    SignatureFieldType,
    SignatureLayout,
    SignatureLayoutRole,
    SignatureRecipient,
    SignatureRequest,
    SignatureRequestField,
)
from bloomerp.models.files.file_node import FileNode


class SigningFixturesMixin:
    """Provide independent stored PDFs, reusable roles, and an editable request."""

    def setUp(self) -> None:
        """Keep PDF bytes in memory and create a request without business records."""
        super().setUp()
        self.enterContext(
            patch.object(
                FileNode._meta.get_field("content"), "storage", InMemoryStorage()
            )
        )
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buffer = BytesIO()
        writer.write(buffer)
        self.pdf_bytes = buffer.getvalue()
        self.digest = sha256(self.pdf_bytes).hexdigest()
        self.now = timezone.now()
        self.original = FileNode.objects.create(
            name="Original.pdf",
            kind="FILE",
            content=ContentFile(self.pdf_bytes, name="original.pdf"),
        )
        self.output = FileNode.objects.create(
            name="Completed.pdf",
            kind="FILE",
            content=ContentFile(self.pdf_bytes, name="completed.pdf"),
        )
        self.folder = FileNode.objects.create(name="Folder", kind="FOLDER")
        self.layout = SignatureLayout.objects.create(name="Two-party agreement")
        self.role = SignatureLayoutRole.objects.create(
            layout=self.layout, key="party_a", label="Party A"
        )
        self.request = SignatureRequest.objects.create(**self.request_args())
        self.recipient = self.create_recipient(self.request)
        self.field = self.create_field(self.recipient)

    def request_args(self, **overrides: Any) -> dict[str, Any]:
        """Build a standalone draft that has no document-template dependency."""
        return {
            "title": "Standalone agreement",
            "original_file": self.original,
            "original_sha256": self.digest,
            **overrides,
        }

    def recipient_args(self, **overrides: Any) -> dict[str, Any]:
        """Build an external recipient for a second independent role."""
        return {
            "request": self.request,
            "role_key": "party_b",
            "role_label": "Party B",
            "name": "Second Signer",
            "email": "second@example.com",
            **overrides,
        }

    def layout_field_args(self, **overrides: Any) -> dict[str, Any]:
        """Build a normalized signature placement owned by the fixture layout."""
        return {
            "layout": self.layout,
            "role": self.role,
            "key": "party_a-signature",
            "field_type": SignatureFieldType.SIGNATURE,
            **overrides,
        }

    def request_field_args(self, **overrides: Any) -> dict[str, Any]:
        """Build a second request-local field for the existing recipient."""
        return {
            "request": self.request,
            "recipient": self.recipient,
            "key": "additional",
            "field_type": SignatureFieldType.TEXT,
            **overrides,
        }

    def create_recipient(
        self,
        request: SignatureRequest,
        role_key: str = "party_a",
        signing_order: int = 1,
    ) -> SignatureRecipient:
        """Create a named signer without creating a Bloomerp user account."""
        return SignatureRecipient.objects.create(
            request=request,
            role_key=role_key,
            role_label=role_key,
            name="External Signer",
            email=f"{role_key}@example.com",
            signing_order=signing_order,
        )

    def create_field(self, recipient: SignatureRecipient) -> SignatureRequestField:
        """Add a required signature field to a draft recipient."""
        return SignatureRequestField.objects.create(
            request_id=recipient.request_id,
            recipient=recipient,
            key=f"{recipient.role_key}-signature",
            field_type=SignatureFieldType.SIGNATURE,
        )

    def populate_request(self, request: SignatureRequest) -> None:
        """Prepare a new request with a recipient and an independent placement."""
        self.create_field(self.create_recipient(request))

    def dispatch_request(self, request: SignatureRequest) -> None:
        """Persist dispatch metadata after the request's recipients are prepared."""
        request.status = SignatureRequest.Status.SENT
        request.sent_at = self.now
        request.save()

    def populate_and_dispatch(self, request: SignatureRequest) -> None:
        """Move a newly created scenario request into the sent state."""
        self.populate_request(request)
        self.dispatch_request(request)

    def fill_recipient_fields(self, recipient: SignatureRecipient) -> None:
        """Complete required fields with drawn ink, text or an explicit checkbox response."""
        for field in recipient.fields.all():
            if field.field_type == SignatureFieldType.SIGNATURE:
                field.value = {
                    "type": "drawn",
                    "version": 1,
                    "strokes": [[[0.1, 0.5], [0.3, 0.2], [0.5, 0.7], [0.8, 0.4]]],
                }
            else:
                field.value = (
                    False
                    if field.field_type == SignatureFieldType.CHECKBOX
                    else "Signed"
                )
            field.filled_at = self.now + timedelta(seconds=1)
            field.save()

    def sign_recipient(self, recipient: SignatureRecipient) -> None:
        """Retain completed values and explicit agreement before recording signing."""
        self.fill_recipient_fields(recipient)
        recipient.consent_text = "I agree to sign this document electronically."
        recipient.consented_at = self.now + timedelta(seconds=2)
        recipient.signed_at = self.now + timedelta(seconds=3)
        recipient.status = SignatureRecipient.Status.SIGNED
        recipient.save()

    def other_request_recipient(self) -> SignatureRecipient:
        """Create a recipient whose request must not own the fixture's evidence."""
        other = SignatureRequest.objects.create(
            **self.request_args(title="Other request")
        )
        return self.create_recipient(other)
