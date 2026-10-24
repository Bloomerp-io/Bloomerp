"""Real PDF pagination through the current and legacy document services."""

from io import BytesIO

from PyPDF2 import PdfReader

from bloomerp.models import DocumentTemplate
from bloomerp.services.document_services import DocumentTemplateService
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.utils.document_templates import DocumentController


class TestDocumentGeneration(BaseBloomerpTestCaseWithModels):
    """Ensure every document-generation entry point uses semantic pagination."""

    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Persist a reusable template containing template variables and a break."""
        self.template = DocumentTemplate.objects.create(
            name="Page break integration",
            template=(
                '<p>Before {{ vars.reference }}</p>'
                '<div data-document-template-page-break="true"></div>'
                '<p>After {{ vars.reference }}</p>'
            ),
            free_variables=[{"slug": "reference", "label": "Reference", "type": "text"}],
            include_page_numbers=False,
        )

    def assert_page_break_pdf(self, pdf_bytes: bytes) -> None:
        """Check the final rendered PDF rather than HTML or a mocked renderer call."""
        self.assertEqual(
            [page.extract_text().strip() for page in PdfReader(BytesIO(pdf_bytes)).pages],
            ["Before Example", "After Example"],
        )

    def test_document_service_renders_variables_across_pages(self) -> None:
        """Generate a fresh document through the validated form-based service."""
        service = DocumentTemplateService(self.template, self.admin_user)
        form = service.get_form()(data={"reference": "Example"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assert_page_break_pdf(service.generate(form))

    def test_legacy_controller_preview_renders_page_breaks(self) -> None:
        """Keep the legacy preview path aligned with service-generated PDFs."""
        controller = DocumentController(user=self.admin_user)
        preview = controller.create_preview_document(
            self.template, {"vars": {"reference": "Example"}}
        )
        self.assert_page_break_pdf(preview.read())

    def test_legacy_controller_generation_renders_page_breaks(self) -> None:
        """Generate a fresh legacy document with the same page boundaries."""
        controller = DocumentController(user=self.admin_user)
        document = controller.create_document(
            self.template, None, free_variables={"reference": "Example"}, persist=False
        )
        self.assert_page_break_pdf(document.read())
