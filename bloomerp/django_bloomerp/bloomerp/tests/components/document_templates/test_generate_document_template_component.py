"""Generated-document persistence contracts through the real component endpoint."""

import base64
from io import BytesIO
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from PyPDF2 import PdfReader

from bloomerp.models import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.files.file_reference import FileReference
from bloomerp.models.project_management.todo import Todo
from bloomerp.services.document_services import DocumentTemplateService
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.utils.pdf import generate_pdf


class TestGenerateDocumentTemplateComponent(BloomerpComponentTestCase):
    """Persist one generated PDF with all selected record and template references."""

    view_name = "components_generate_document_template"
    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Provide two source models and isolate only the external PDF renderer."""
        self.customer = self.create_customer("Document", "Owner", 30)
        self.todo = Todo.objects.create(title="Source task")
        self.template = DocumentTemplate.objects.create(name="Contract")
        self.template.content_types.add(
            ContentType.objects.get_for_model(self.customer),
            ContentType.objects.get_for_model(self.todo),
        )
        self.service = DocumentTemplateService(self.template, self.admin_user)
        self.pdf_bytes = b"%PDF-test source bytes"
        self.pdf_renderer = self.enterContext(patch(
            "bloomerp.services.document_services.generate_pdf", return_value=self.pdf_bytes
        ))

    def prepare_real_page_break_rendering(self, scenario: RequestScenario) -> None:
        """Use WeasyPrint for a stored template with an explicit semantic break."""
        self.pdf_renderer.side_effect = generate_pdf
        self.template.template = (
            '<p>Before</p><div data-document-template-page-break="true"></div><p>After</p>'
        )
        self.template.include_page_numbers = False
        self.template.save(update_fields=["template", "include_page_numbers"])

    def validate_real_page_break_preview(self, response: HttpResponse) -> bool:
        """Decode the actual preview PDF and verify exact content on each page."""
        self.preview_bytes = base64.b64decode(response.context["file_bytes"])
        self.assertEqual(
            [page.extract_text().strip() for page in PdfReader(BytesIO(self.preview_bytes)).pages],
            ["Before", "After"],
        )
        self.assertContains(
            response,
            f'data:application/pdf;base64,{response.context["file_bytes"]}',
        )
        return True

    def validate_real_page_break_persistence(self, response: HttpResponse) -> bool:
        """Verify that the downloadable saved file is the freshly generated preview."""
        self.validate_real_page_break_preview(response)
        node = FileNode.objects.get()
        self.assertEqual(node.content.read(), self.preview_bytes)
        self.assertEqual(node.metadata.size, len(self.preview_bytes))
        self.assertEqual(node.references.count(), 3)
        return True

    def validate_preview_has_no_saved_files(self, response: HttpResponse) -> bool:
        """Keep preview-only generation free of stored files and source references."""
        self.assertFalse(FileNode.objects.exists())
        self.assertFalse(FileReference.objects.exists())
        return True

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover all selected objects, preset objects, and generation without saving."""
        data = {"customer": str(self.customer.pk), "todo": str(self.todo.pk)}
        return [
            RequestScenario(
                name="Save one PDF referencing both selected models and its template",
                method="POST",
                user=self.admin_user,
                view_kwargs={"id": str(self.template.pk)},
                data={**data, "persist": "on"},
                expected=ExpectedResult(response_validators=[
                    lambda response: FileNode.objects.count() == 1,
                    lambda response: set(FileReference.objects.values_list(
                        "content_type_id", "object_id"
                    )) == {
                        (ContentType.objects.get_for_model(obj).pk, str(obj.pk))
                        for obj in (self.template, self.customer, self.todo)
                    },
                    lambda response: FileNode.objects.get().content.read() == self.pdf_bytes,
                    lambda response: FileNode.objects.get().metadata.size == len(self.pdf_bytes),
                    lambda response: FileNode.objects.get().parent_id is None,
                    lambda response: list(self.service.get_files(self.customer))
                    == list(self.service.get_files(self.todo))
                    == [FileNode.objects.get()],
                ]),
            ),
            RequestScenario(
                name="Preset object and selected object both receive references",
                method="POST",
                user=self.admin_user,
                view_kwargs={"id": str(self.template.pk)},
                query_params={
                    "content_type_id": ContentType.objects.get_for_model(self.customer).pk,
                    "object_id": str(self.customer.pk),
                },
                data={"todo": str(self.todo.pk), "persist": "on"},
                expected=ExpectedResult(response_validators=[
                    lambda response: FileReference.objects.count() == 3,
                    lambda response: self.service.get_files(self.customer).exists(),
                    lambda response: self.service.get_files(self.todo).exists(),
                ]),
            ),
            RequestScenario(
                name="Preview without persistence does not create nodes or references",
                method="POST",
                user=self.admin_user,
                view_kwargs={"id": str(self.template.pk)},
                data=data,
                expected=ExpectedResult(response_validators=lambda response: (
                    not FileNode.objects.exists() and not FileReference.objects.exists()
                )),
            ),
            RequestScenario(
                name="Render a real multi-page PDF preview from a saved page-break template",
                method="POST",
                user=self.admin_user,
                view_kwargs={"id": str(self.template.pk)},
                data=data,
                prepare=self.prepare_real_page_break_rendering,
                expected=ExpectedResult(response_validators=[
                    self.validate_real_page_break_preview,
                    self.validate_preview_has_no_saved_files,
                ]),
            ),
            RequestScenario(
                name="Save the real multi-page PDF with its source references",
                method="POST",
                user=self.admin_user,
                view_kwargs={"id": str(self.template.pk)},
                data={**data, "persist": "on"},
                prepare=self.prepare_real_page_break_rendering,
                expected=ExpectedResult(response_validators=self.validate_real_page_break_persistence),
            ),
        ]

    def test_duplicate_sources_and_template_only_documents(self) -> None:
        """Deduplicate repeated sources and retain documents with no source objects."""
        node = self.service.create_file(
            self.pdf_bytes,
            objects=[self.customer, self.customer, self.template],
            filename="contract",
        )
        self.assertEqual(node.references.count(), 2)
        self.assertEqual(node.name, "contract.pdf")
        self.assertFalse(self.service.get_files(self.todo).exists())
        template_only = self.service.create_file(self.pdf_bytes)
        self.assertEqual(template_only.references.count(), 1)
        self.assertEqual(set(self.service.get_files()), {node, template_only})

    def test_reference_failure_removes_node_and_bytes(self) -> None:
        """Roll back the node and earlier references if a later source is invalid."""
        from django.core.exceptions import ValidationError

        storage = FileNode._meta.get_field("content").storage
        with (
            patch.object(storage, "delete", wraps=storage.delete) as delete,
            self.assertRaises(ValidationError),
        ):
            self.service.create_file(self.pdf_bytes, objects=[Todo(title="Unsaved")])
        self.assertFalse(FileNode.objects.exists())
        self.assertFalse(FileReference.objects.exists())
        delete.assert_called_once()
        self.assertFalse(storage.exists(delete.call_args.args[0]))
