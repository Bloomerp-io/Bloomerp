from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import FileNode, FileReference
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFileFieldLifecycle(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def test_upload_waits_for_parent_save(self) -> None:
        """
        Use case: A valid file editor is saved with commit=False.
        Expected result: Uploads remain pending until the saved parent's structured fields save.
        """
        # 1. Validate a new-object form without creating file records.
        form_class = bloomerp_modelform_factory(
            self.CustomerModel, fields=["first_name", "last_name", "age", "picture"]
        )
        form = form_class(
            data={
                "first_name": "New",
                "last_name": "Customer",
                "age": 30,
                "picture__present": "1",
            },
            files={"picture": SimpleUploadedFile("file.pdf", b"pdf")},
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(FileNode.objects.count(), 0)
        # 2. Save the parent without creating pending uploads.
        parent = form.save(commit=False)
        self.assertEqual(FileNode.objects.count(), 0)
        parent.save()
        # 3. Persist structured files once, with the new parent's real ID.
        form.save_structured_fields()
        form.save_structured_fields()
        parent.refresh_from_db()
        self.assertEqual(len(parent.picture), 1)
        self.assertEqual(
            FileNode.objects.get(pk=parent.picture[0].pk).references.get().object_id,
            str(parent.pk),
        )
        self.assertEqual(
            form.serialize_cleaned_data()["picture"],
            [str(file.pk) for file in parent.picture],
        )

    def test_removal_only_unlinks_owning_field(self) -> None:
        """
        Use case: Clearing a field unlinks its usage while preserving stored bytes and generic uploads.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        customer = self.create_customer("Direct", "Save", 30)
        field = self.CustomerModel._meta.get_field("picture")
        field.on_save(customer, [], [SimpleUploadedFile("field.pdf", b"pdf")])
        attachment = customer.picture[0]
        generic = FileNode.objects.create(
            content=SimpleUploadedFile("generic.pdf", b"pdf"),
            kind="FILE",
        )
        FileReference.objects.create(file=generic, content_object=customer)
        customer.save(update_fields=["first_name"])
        self.assertTrue(FileNode.objects.filter(pk=attachment.pk).exists())
        field.on_save(customer, [], [])
        self.assertTrue(FileNode.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(attachment.references.exists())
        self.assertTrue(attachment.content.storage.exists(attachment.content.name))
        self.assertTrue(FileNode.objects.filter(pk=generic.pk).exists())

    def test_file_browser_links_to_field_with_htmx_and_preview(self) -> None:
        """
        Use case: The file browser displays an attachment belonging to a named field.
        Expected result: Object navigation includes the field fragment, HTMX target, and preview IDs.
        """
        from types import SimpleNamespace

        from bs4 import BeautifulSoup
        from django.test import RequestFactory

        from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer
        from bloomerp.models import ApplicationField
        from bloomerp.models.files.file_node import FileNode
        from bloomerp.models.files.file_reference import FileReference

        customer = self.create_customer("Linked", "Customer", 30)
        file = FileNode.objects.create(
            name="field.pdf",
            kind="FILE",
            content=SimpleUploadedFile("field.pdf", b"pdf"),
        )
        FileReference.objects.create(
            file=file,
            content_object=customer,
            application_field=ApplicationField.get_by_field(
                self.CustomerModel, "picture"
            ),
        )
        request = RequestFactory().get("/")
        request.user = self.admin_user
        renderer = FileBrowserRenderer(
            SimpleNamespace(
                request=request,
                model=FileNode,
                options=None,
                queryset=FileNode.objects.filter(pk=file.pk),
            )
        )
        files, _entries = renderer._visible_entries()
        html = render_to_string(
            "dataviews/files.html", {"files": files, "file_actions": []}
        )
        link = BeautifulSoup(html, "html.parser").select_one(
            "a[data-preview-object-id]"
        )
        # 3. Check navigation, label, and reused preview wiring.
        self.assertIsNotNone(link)
        self.assertEqual(link["href"], f"{customer.get_absolute_url()}#picture")
        self.assertEqual(link["hx-get"], link["href"])
        self.assertEqual(link["hx-target"], "#main-content")
        self.assertEqual(link["data-preview-object-id"], str(customer.pk))
        self.assertIn("(Picture)", link.get_text())

    def test_partial_update_preserves_omitted_attachments(self) -> None:
        """
        Use case: A partial edit omits a file editor that already has an attachment.
        Expected result: The existing ID and stored file remain unchanged.
        """
        from django.http import QueryDict

        # 1. Attach a file and build a form that includes its editor.
        customer = self.create_customer("Partial", "Edit", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer, [], [SimpleUploadedFile("keep.pdf", b"pdf")]
        )
        original_ids = list(customer.picture)
        form_class = bloomerp_modelform_factory(
            self.CustomerModel, fields=["first_name", "picture"]
        )
        # 2. Prepare a partial submission containing only an unrelated field.
        data = form_class.prepare_bound_data(
            QueryDict("first_name=Updated"), {}, customer, partial=True
        )
        form = form_class(data=data, instance=customer)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        # 3. Verify the unrelated change succeeds without removing the attachment.
        customer.refresh_from_db()
        self.assertEqual(customer.first_name, "Updated")
        self.assertEqual(customer.picture, original_ids)
        self.assertTrue(FileNode.objects.filter(pk=original_ids[0].pk).exists())

    def test_referenced_file_cannot_be_deleted(self) -> None:
        """Protect stored content while a field reference still uses it."""
        from django.db.models.deletion import ProtectedError

        customer = self.create_customer("File", "Deletion", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer, [], [SimpleUploadedFile("delete.pdf", b"pdf")]
        )
        with self.assertRaises(ProtectedError):
            customer.picture[0].delete()
        customer.refresh_from_db()
        self.assertEqual(len(customer.picture), 1)

    def test_shared_attachment_survives_field_removal(self) -> None:
        """Removing a field usage retains the same node on another object's files."""
        source = self.create_customer("Source", "Customer", 30)
        target = self.create_customer("Target", "Customer", 30)
        field = self.CustomerModel._meta.get_field("picture")
        field.on_save(source, [], [SimpleUploadedFile("shared.pdf", b"pdf")])
        file = source.picture[0]
        reference = FileReference.objects.create(file=file, content_object=target)
        field.on_save(source, [], [])
        source.refresh_from_db()
        self.assertEqual(source.picture, [])
        self.assertEqual(list(target.files.all()), [reference])
        self.assertTrue(file.content.storage.exists(file.content.name))

    def test_parent_deletion_cleans_references_and_preserves_storage(self) -> None:
        """
        Use case: Deleting a parent removes its references while preserving file nodes and bytes.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from bloomerp.models import FileReference

        customer = self.create_customer("Owner", "Delete", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("owned.pdf", b"pdf")],
        )
        file = customer.picture[0]
        customer.delete()
        self.assertFalse(FileReference.objects.filter(file_id=file.pk).exists())
        self.assertTrue(FileNode.objects.filter(pk=file.pk).exists())
        self.assertTrue(file.content.storage.exists(file.content.name))

    def test_application_field_deletion_cleans_references_and_preserves_storage(
        self,
    ) -> None:
        """
        Use case: Discarding an application field cascades its references while preserving nodes.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from bloomerp.models import ApplicationField, FileReference

        customer = self.create_customer("Field", "Delete", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("owned.pdf", b"pdf")],
        )
        file = customer.picture[0]
        ApplicationField.get_by_field(self.CustomerModel, "picture").delete()
        self.assertFalse(FileReference.objects.filter(file_id=file.pk).exists())
        self.assertTrue(FileNode.objects.filter(pk=file.pk).exists())
        self.assertTrue(file.content.storage.exists(file.content.name))

    def test_virtual_field_has_no_parent_database_column(self) -> None:
        """
        Use case: A file declaration uses the shared table without changing the parent schema.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from django.db import connection

        field = self.CustomerModel._meta.get_field("picture")
        self.assertFalse(field.concrete)
        self.assertIn(field, self.CustomerModel._meta.private_fields)
        with connection.cursor() as cursor:
            columns = connection.introspection.get_table_description(
                cursor, self.CustomerModel._meta.db_table
            )
        self.assertNotIn("picture", {column.name for column in columns})
        self.assertNotIn("picture_id", {column.name for column in columns})

    def test_collection_values_load_in_one_query(self) -> None:
        """
        Use case: A page of attachment values uses one batch query and renders without more lookups.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from bloomerp.field_types.utils.value_loading import prepare_field_values
        from bloomerp.models import ApplicationField

        field = self.CustomerModel._meta.get_field("picture")
        for index in range(3):
            customer = self.create_customer(f"Batch{index}", "Files", 30)
            field.on_save(customer, [], [SimpleUploadedFile(f"{index}.pdf", b"pdf")])
        objects = list(self.CustomerModel.objects.all())
        application_field = ApplicationField.get_by_field(self.CustomerModel, "picture")
        application_field.get_field_type()
        with self.assertNumQueries(1):
            prepare_field_values(objects, [application_field])
        with self.assertNumQueries(0):
            for customer in objects:
                self.assertEqual(len(customer.picture), 1)
                self.assertIn(
                    ".pdf",
                    application_field.get_field_type().render_value(
                        application_field, customer
                    ),
                )

    def test_one_file_can_have_multiple_field_usages(self) -> None:
        """Sharing a node across objects creates separate field-scoped references."""
        customer = self.create_customer("First", "Owner", 30)
        other = self.create_customer("Second", "Owner", 31)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer, [], [SimpleUploadedFile("shared.pdf", b"pdf")]
        )
        file = customer.picture[0]
        reference = file.references.get()
        FileReference.objects.create(
            file=file,
            content_object=other,
            application_field=reference.application_field,
        )
        self.assertEqual(other.picture, [file])
        self.assertEqual(file.references.count(), 2)

    def test_hidden_field_values_are_not_loaded(self) -> None:
        """
        Use case: Field access annotations hide a file field on one displayed row.
        Expected result: Batched preparation leaves that row's attachment cache empty.
        """
        from bloomerp.field_types.utils.value_loading import prepare_field_values
        from bloomerp.models import ApplicationField
        from bloomerp.permissions.manager import field_access_annotation_name

        # 1. Create a field-owned attachment and mark the field as hidden.
        customer = self.create_customer("Hidden", "Files", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("hidden.pdf", b"pdf")],
        )
        application_field = ApplicationField.get_by_field(self.CustomerModel, "picture")
        setattr(customer, field_access_annotation_name(application_field), False)
        # 2. Prepare and read the denied field without loading its references.
        prepare_field_values([customer], [application_field])
        with self.assertNumQueries(0):
            self.assertEqual(customer.picture, [])

    def test_multiple_file_fields_share_one_batch_query(self) -> None:
        """
        Use case: A page displays two different attachment fields on each object.
        Expected result: Both fields load together through the generic field hook.
        """
        from django.contrib.contenttypes.models import ContentType

        from bloomerp.field_types.utils.value_loading import prepare_field_values
        from bloomerp.model_fields.file_field import BloomerpFileField
        from bloomerp.models import ApplicationField

        # 1. Declare another virtual file field without altering the parent table.
        self.CustomerModel.add_to_class("documents", BloomerpFileField(multiple=True))
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        ApplicationField.objects.create(
            content_type=content_type,
            field="documents",
            field_type="BloomerpFileField",
        )
        customer = self.create_customer("Two", "Fields", 30)
        for name in ("picture", "documents"):
            self.CustomerModel._meta.get_field(name).on_save(
                customer,
                [],
                [SimpleUploadedFile(f"{name}.pdf", b"pdf")],
            )
        # 2. Load fresh objects and application fields as a collection page does.
        objects = list(self.CustomerModel.objects.all())
        fields = list(
            ApplicationField.get_for_model(self.CustomerModel).filter(
                field__in=["picture", "documents"]
            )
        )
        with self.assertNumQueries(1):
            prepare_field_values(objects, fields)
        # 3. Both descriptors now read their cached File records without queries.
        with self.assertNumQueries(0):
            self.assertEqual(len(objects[0].picture), 1)
            self.assertEqual(len(objects[0].documents), 1)

    def test_scoped_file_browser_includes_field_owned_files(self) -> None:
        """A host collection includes nodes referenced through an attachment field."""
        from types import SimpleNamespace

        from django.contrib.contenttypes.models import ContentType
        from django.test import RequestFactory

        from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer
        from bloomerp.models import ApplicationField
        from bloomerp.models.files.file_node import FileNode
        from bloomerp.models.files.file_reference import FileReference

        customer = self.create_customer("Scoped", "Browser", 30)
        file = FileNode.objects.create(
            name="scoped.pdf",
            kind="FILE",
            content=SimpleUploadedFile("scoped.pdf", b"pdf"),
        )
        FileReference.objects.create(
            file=file,
            content_object=customer,
            application_field=ApplicationField.get_by_field(
                self.CustomerModel, "picture"
            ),
        )
        request = RequestFactory().get("/")
        request.user = self.admin_user
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        state = SimpleNamespace(
            request=request,
            model=self.CustomerModel,
            options=None,
            queryset=self.CustomerModel.objects.filter(pk=customer.pk),
            content_type=content_type,
            content_type_id=content_type.pk,
            query=None,
        )
        files, _entries = FileBrowserRenderer(state)._visible_entries()
        self.assertEqual([item.pk for item in files], [file.pk])
        self.assertEqual(files[0].browser_owners[0]["object_id"], str(customer.pk))

    def test_required_virtual_upload_validates_before_persistence(self) -> None:
        """
        Use case: A required virtual file field has a valid upload on a file-only form.
        Expected result: Validation succeeds before reference creation and rejects an empty upload.
        """
        # 1. Configure a required field on an existing object without an attachment.
        customer = self.create_customer("Required", "Upload", 30)
        field = self.CustomerModel._meta.get_field("picture")
        self.addCleanup(setattr, field, "blank", field.blank)
        field.blank = False
        form_class = bloomerp_modelform_factory(self.CustomerModel, fields=["picture"])
        form = form_class(
            data={"picture__present": "1"},
            instance=customer,
            files={"picture": SimpleUploadedFile("required.pdf", b"pdf")},
        )
        # 2. Validate the pending structured value before Django saves the parent.
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(FileNode.objects.count(), 0)
        form.save()
        self.assertEqual(len(customer.picture), 1)
        # 3. Required validation still rejects explicitly clearing the field.
        empty = form_class(data={"picture__present": "1"}, instance=customer)
        self.assertFalse(empty.is_valid())
        self.assertIn("picture", empty.errors)

    def test_files_relation_targets_shared_references(self) -> None:
        """The generic files relation uses references without adding a parent column."""
        field = self.CustomerModel._meta.get_field("files")
        self.assertIs(field.related_model, FileReference)
        self.assertIn(field, self.CustomerModel._meta.private_fields)

    def test_generic_files_uploads_are_deferred_and_idempotent(self) -> None:
        """Generic files create nodes and manual references only after saving the parent."""
        from bloomerp.form_fields.files_relation_field import FilesRelationField

        customer = self.create_customer("Generic", "Uploads", 30)
        value = FilesRelationField().clean(
            [SimpleUploadedFile("manual.txt", b"manual")]
        )
        self.assertEqual(FileNode.objects.count(), 0)
        value.save(customer, user=self.admin_user)
        value.save(customer, user=self.admin_user)
        reference = customer.files.get()
        self.assertIsNone(reference.application_field_id)
        self.assertIsNone(reference.occurrence_id)
        self.assertIsNone(reference.file.parent_id)
        self.assertEqual(reference.file.metadata.size, 6)
        self.assertEqual(reference.file.created_by_id, self.admin_user.pk)
        self.assertEqual(FileNode.objects.count(), 1)
        customer.delete()
        self.assertFalse(FileReference.objects.filter(pk=reference.pk).exists())
        self.assertTrue(FileNode.objects.filter(pk=reference.file_id).exists())

    def test_generic_files_display_excludes_named_field_references(self) -> None:
        """The generic files widget and collection value never expose a named field's files."""
        from bloomerp.field_types.utils.file_values import render_object_files_value
        from bloomerp.models import ApplicationField
        from bloomerp.widgets.object_files_widget import ObjectFilesWidget

        customer = self.create_customer("Scoped", "Display", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer, [], [SimpleUploadedFile("private.pdf", b"private")]
        )
        node = FileNode.objects.create(
            kind="FILE", content=SimpleUploadedFile("manual.txt", b"manual")
        )
        reference = FileReference.objects.create(file=node, content_object=customer)
        widget = ObjectFilesWidget()
        self.assertEqual(widget.format_value(customer.files), [node])
        self.assertEqual(widget.format_value(list(customer.files.all())), [node])
        rendered = render_object_files_value(
            ApplicationField.get_by_field(self.CustomerModel, "files"), customer
        )
        self.assertIn("manual.txt", rendered)
        self.assertNotIn("private.pdf", rendered)
        reference.delete()
        customer.refresh_from_db()
        self.assertEqual(len(customer.picture), 1)

    def test_legacy_deletion_preserves_migrated_storage(self) -> None:
        """Legacy cleanup cannot remove a storage key still used by a migrated node."""
        from bloomerp.models import File

        legacy = File.objects.create(file=SimpleUploadedFile("legacy.txt", b"legacy"))
        node = FileNode.objects.create(
            pk=legacy.pk, kind="FILE", content=legacy.file.name
        )
        legacy.delete()
        self.assertTrue(node.content.storage.exists(node.content.name))

    def test_reviewed_submission_references_original_upload(self) -> None:
        """Persisting a public submission shares its node with the resulting object."""
        from unittest.mock import patch

        from django.contrib.contenttypes.models import ContentType

        from bloomerp.form_fields.files_relation_field import FilesCleanedData
        from bloomerp.models.forms.form import Form
        from bloomerp.models.forms.form_submission import FormSubmission
        from bloomerp.services.form_services import FormManager

        form = Form.objects.create(
            name="Public attachments",
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
        )
        submission = FormSubmission.objects.create(
            form=form,
            data={"first_name": "Submitted", "last_name": "Customer", "age": 30},
        )
        FilesCleanedData(
            files=[SimpleUploadedFile("submitted.txt", b"submission")]
        ).save(submission)
        node = submission.files.get().file
        manager = FormManager(form)
        form_class = bloomerp_modelform_factory(
            self.CustomerModel, fields=["first_name", "last_name", "age"]
        )
        with patch.object(manager, "layout_form_cls", return_value=form_class):
            manager.persist_form_submission(submission)
            manager.persist_form_submission(submission)
        target = self.CustomerModel.objects.get(first_name="Submitted")
        self.assertEqual(target.files.get().file_id, node.pk)
        self.assertEqual(submission.files.get().file_id, node.pk)
        self.assertEqual(node.references.count(), 2)
        self.assertEqual(FileNode.objects.count(), 1)

    def test_failed_reference_creation_cleans_new_upload_bytes(self) -> None:
        """A failed reference insert rolls back the node and deletes only its new bytes."""
        from unittest.mock import patch

        from django.core.exceptions import ValidationError
        from django.core.files.storage import InMemoryStorage

        customer = self.create_customer("Failed", "Upload", 30)
        storage = InMemoryStorage()
        with (
            patch.object(FileNode._meta.get_field("content"), "storage", storage),
            patch.object(
                FileReference.objects, "create", side_effect=ValidationError("Rejected")
            ),
            self.assertRaises(ValidationError),
        ):
            self.CustomerModel._meta.get_field("picture").on_save(
                customer, [], [SimpleUploadedFile("failed.txt", b"failed")]
            )
        self.assertEqual(FileNode.objects.count(), 0)
        self.assertEqual(storage.listdir("bloomerp/files")[1], [])
