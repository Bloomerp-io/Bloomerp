"""Generated-document persistence contracts through the real component endpoint."""

from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType

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
        self.enterContext(patch(
            "bloomerp.services.document_services.generate_pdf", return_value=self.pdf_bytes
        ))

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
