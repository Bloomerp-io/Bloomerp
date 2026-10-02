from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.document_templates.document_template_header import (
    DocumentTemplateHeader,
)
from bloomerp.services.bulk_services import BulkCrudService
from bloomerp.services.document_services import DocumentTemplateService
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFileProvenance(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def test_generated_documents_use_typed_provenance(self) -> None:
        """
        Use case: A document template creates a PDF for an object.
        Expected result: Provenance validates and template file lookup finds the created file.
        """
        # 1. Create a real document template and target object.
        customer = self.create_customer("Document", "Owner", 30)
        header = DocumentTemplateHeader.objects.create(
            name="Header", header="header.png"
        )
        template = DocumentTemplate.objects.create(
            name="Contract", template_header=header
        )
        template.content_types.add(ContentType.objects.get_for_model(customer))
        service = DocumentTemplateService(template, self.admin_user)
        # 2. Persist a generated document through the production service.
        file = service.create_file(
            b"%PDF-test", instance=customer, filename="contract.pdf"
        )
        # 3. Verify validated metadata and the nested provenance query.
        self.assertEqual(file.metadata.document_template.id, template.pk)
        self.assertEqual(file.metadata.document_template.name, "Contract")
        self.assertEqual(list(service.get_files(customer)), [file])

    def test_bulk_draft_uses_typed_provenance(self) -> None:
        """
        Use case: A CSV upload creates a bulk-import draft.
        Expected result: Typed draft metadata preserves its source identity and supports lookup.
        """
        # 1. Build a valid CSV source for the customer model.
        service = BulkCrudService(model=self.CustomerModel, user=self.admin_user)
        upload = SimpleUploadedFile(
            "customers.csv",
            b"first_name,last_name,age\nAda,Example,35\n",
            content_type="text/csv",
        )
        # 2. Create and load a draft through the production service.
        draft = service.create_draft(upload)
        file = service.get_draft_file(draft.file_id)
        # 3. Verify the nested provenance and source rows are preserved.
        self.assertIsNotNone(file)
        self.assertEqual(
            file.metadata.bulk_upload.model_label, self.CustomerModel._meta.label_lower
        )
        self.assertEqual(file.metadata.bulk_upload.original_filename, "customers.csv")
        rows, fields = service.get_source_rows(file)
        self.assertEqual(rows[0]["first_name"], "Ada")
        self.assertIn("age", fields)

    def test_legacy_document_controller_uses_typed_provenance(self) -> None:
        """
        Use case: The legacy document controller renders and stores a generated PDF.
        Expected result: Its metadata validates and preserves the template identity.
        """
        from unittest.mock import patch

        from bloomerp.utils.document_templates import DocumentController

        # 1. Provide a real template and object while isolating the PDF renderer.
        customer = self.create_customer("Legacy", "Document", 30)
        header = DocumentTemplateHeader.objects.create(
            name="Header", header="header.png"
        )
        template = DocumentTemplate.objects.create(
            name="Contract", template_header=header
        )
        with patch(
            "bloomerp.utils.document_templates.generate_pdf", return_value=b"%PDF-test"
        ):
            file = DocumentController(user=self.admin_user).create_document(
                template, customer
            )
        # 2. Verify the legacy entry point now produces the shared typed schema.
        self.assertEqual(file.metadata.document_template.id, template.pk)
        self.assertFalse(file.metadata.signature.signed)
        self.assertTrue(file.persisted)

    def test_signing_preserves_template_provenance(self) -> None:
        """
        Use case: A generated PDF is signed through the legacy controller.
        Expected result: Source and signed output retain template provenance and typed signature data.
        """
        from unittest.mock import patch

        from bloomerp.utils.document_templates import DocumentController

        # 1. Create a generated PDF with current typed template metadata.
        customer = self.create_customer("Signed", "Document", 30)
        header = DocumentTemplateHeader.objects.create(
            name="Header", header="header.png"
        )
        template = DocumentTemplate.objects.create(
            name="Contract", template_header=header
        )
        file = DocumentTemplateService(template, self.admin_user).create_file(
            b"%PDF-source",
            instance=customer,
            filename="contract.pdf",
        )
        # 2. Sign through the production lifecycle while isolating the PDF engine.
        with patch("bloomerp.utils.document_templates.PdfHandler") as handler:
            handler.return_value.sign_pdf.return_value = b"%PDF-signed"
            signed = DocumentController(user=self.admin_user).sign_pdf(
                file, b"signature"
            )
        # 3. Both records keep provenance and expose the output/signer through typed metadata.
        file.refresh_from_db()
        self.assertEqual(file.metadata.document_template.id, template.pk)
        self.assertEqual(file.metadata.signature.signed_file_id, signed.pk)
        self.assertEqual(signed.metadata.document_template.id, template.pk)
        self.assertEqual(signed.metadata.signature.user_id, self.admin_user.pk)
        self.assertTrue(signed.metadata.signature.signed)
        self.assertTrue(signed.persisted)
