from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import File
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
        self.assertEqual(File.objects.count(), 0)
        # 2. Save the parent without creating pending uploads.
        parent = form.save(commit=False)
        self.assertEqual(File.objects.count(), 0)
        parent.save()
        # 3. Persist structured files once, with the new parent's real ID.
        form.save_structured_fields()
        form.save_structured_fields()
        parent.refresh_from_db()
        self.assertEqual(len(parent.picture), 1)
        self.assertEqual(
            File.objects.get(pk=parent.picture[0].pk).field_reference.object_id,
            str(parent.pk),
        )
        self.assertEqual(
            form.serialize_cleaned_data()["picture"],
            [str(file.pk) for file in parent.picture],
        )

    def test_removal_only_deletes_owning_field_files(self) -> None:
        """
        Use case: Clearing a field deletes its files and bytes while preserving generic uploads.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        customer = self.create_customer("Direct", "Save", 30)
        field = self.CustomerModel._meta.get_field("picture")
        field.on_save(customer, [], [SimpleUploadedFile("field.pdf", b"pdf")])
        attachment = customer.picture[0]
        generic = File.objects.create(
            file=SimpleUploadedFile("generic.pdf", b"pdf"),
            persisted=True,
            content_object=customer,
        )
        customer.save(update_fields=["first_name"])
        self.assertTrue(File.objects.filter(pk=attachment.pk).exists())
        field.on_save(customer, [], [])
        self.assertFalse(File.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(attachment.file.storage.exists(attachment.file.name))
        self.assertTrue(File.objects.filter(pk=generic.pk).exists())

    def test_file_browser_links_to_field_with_htmx_and_preview(self) -> None:
        """
        Use case: The file browser displays an attachment belonging to a named field.
        Expected result: Object navigation includes the field fragment, HTMX target, and preview IDs.
        """
        from bs4 import BeautifulSoup

        # 1. Create an attachment linked to a detail object's picture field.
        customer = self.create_customer("Linked", "Customer", 30)
        field = self.CustomerModel._meta.get_field("picture")
        field.on_save(customer, [], [SimpleUploadedFile("field.pdf", b"pdf")])
        file = File.objects.get(pk=customer.picture[0].pk)
        # 2. Render the actual file browser markup.
        html = render_to_string(
            "dataviews/files.html", {"files": [file], "file_actions": []}
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
        self.assertTrue(File.objects.filter(pk=original_ids[0].pk).exists())

    def test_file_deletion_clears_the_owning_field_reference(self) -> None:
        """
        Use case: A field attachment is deleted using a file-browser action.
        Expected result: The parent field contains no stale ID after deletion.
        """
        # 1. Create a field attachment.
        customer = self.create_customer("File", "Deletion", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer, [], [SimpleUploadedFile("delete.pdf", b"pdf")]
        )
        # 2. Delete its File record through the model lifecycle used by browser actions.
        File.objects.get(pk=customer.picture[0].pk).delete()
        # 3. Check the owning field no longer refers to the deleted record.
        customer.refresh_from_db()
        self.assertEqual(customer.picture, [])

    def test_moving_attachment_detaches_its_original_field(self) -> None:
        """
        Use case: A field attachment is moved to a different object's files.
        Expected result: The old field is cleared and the moved file has generic provenance.
        """
        # 1. Create the source attachment and target object.
        source = self.create_customer("Source", "Customer", 30)
        target = self.create_customer("Target", "Customer", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            source, [], [SimpleUploadedFile("move.pdf", b"pdf")]
        )
        file = File.objects.get(pk=source.picture[0].pk)
        # 2. Reassign the attachment through the existing move API.
        File.move_files_to_object(target, [file])
        # 3. Verify source references and destination metadata remain consistent.
        source.refresh_from_db()
        file.refresh_from_db()
        self.assertEqual(source.picture, [])
        self.assertFalse(hasattr(file, "field_reference"))
        self.assertEqual(file.object_id, str(target.pk))

    def test_parent_deletion_cleans_references_and_storage(self) -> None:
        """
        Use case: Deleting a parent removes every owned reference, file record, and stored byte.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from bloomerp.models import FileFieldReference

        customer = self.create_customer("Owner", "Delete", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("owned.pdf", b"pdf")],
        )
        file = customer.picture[0]
        customer.delete()
        self.assertFalse(FileFieldReference.objects.filter(file_id=file.pk).exists())
        self.assertFalse(File.objects.filter(pk=file.pk).exists())
        self.assertFalse(file.file.storage.exists(file.file.name))

    def test_application_field_deletion_cleans_references_and_storage(self) -> None:
        """
        Use case: Discarding an application field cascades its references and owned files.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from bloomerp.models import ApplicationField, FileFieldReference

        customer = self.create_customer("Field", "Delete", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("owned.pdf", b"pdf")],
        )
        file = customer.picture[0]
        ApplicationField.get_by_field(self.CustomerModel, "picture").delete()
        self.assertFalse(FileFieldReference.objects.filter(file_id=file.pk).exists())
        self.assertFalse(File.objects.filter(pk=file.pk).exists())
        self.assertFalse(file.file.storage.exists(file.file.name))

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

    def test_one_file_cannot_have_two_owners(self) -> None:
        """
        Use case: The database enforces one field reference per file across all objects.
        Expected result: The reference-backed lifecycle maintains this contract.
        """
        from django.db import IntegrityError, transaction

        from bloomerp.models import FileFieldReference

        customer = self.create_customer("Unique", "Owner", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("unique.pdf", b"pdf")],
        )
        reference = customer.picture[0].field_reference
        with self.assertRaises(IntegrityError), transaction.atomic():
            FileFieldReference.objects.create(
                file_id=reference.file_id,
                application_field=reference.application_field,
                object_id=str(customer.pk),
            )

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
        """
        Use case: An object's file browser uses historical generic-file scope filters.
        Expected result: It also includes files owned through the new reference table.
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        from django.contrib.contenttypes.models import ContentType
        from django.test import RequestFactory

        from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer

        # 1. Create a field file excluded by the old generic owner columns.
        customer = self.create_customer("Scoped", "Browser", 30)
        self.CustomerModel._meta.get_field("picture").on_save(
            customer,
            [],
            [SimpleUploadedFile("scoped.pdf", b"pdf")],
        )
        file = customer.picture[0]
        request = RequestFactory().get("/")
        request.user = self.admin_user
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        state = SimpleNamespace(
            request=request,
            model=File,
            options=None,
            queryset=File.objects.filter(
                content_type=content_type, object_id=str(customer.pk)
            ),
        )
        # 2. Resolve the same host scope the detail file tab supplies.
        renderer = FileBrowserRenderer(state)
        with (
            patch(
                "bloomerp.dataviews.file_browser.renderer._resolve_content_type",
                return_value=content_type,
            ),
            patch(
                "bloomerp.dataviews.file_browser.renderer._resolve_object",
                return_value=customer,
            ),
        ):
            _folder, _folders, files = renderer._get_file_model_items(file.folder)
        # 3. Check canonical ownership is included and the owner was batch-loaded.
        self.assertEqual([item.pk for item in files], [file.pk])
        with self.assertNumQueries(0):
            self.assertEqual(files[0].linked_object.pk, customer.pk)

    def test_required_virtual_upload_validates_before_persistence(self) -> None:
        """
        Use case: A required virtual file field has a valid upload on a file-only form.
        Expected result: Validation succeeds before reference creation and rejects an empty upload.
        """
        # 1. Configure a required field on an existing object without an attachment.
        customer = self.create_customer("Required", "Upload", 30)
        self.CustomerModel._meta.get_field("picture").blank = False
        form_class = bloomerp_modelform_factory(self.CustomerModel, fields=["picture"])
        form = form_class(
            data={"picture__present": "1"},
            instance=customer,
            files={"picture": SimpleUploadedFile("required.pdf", b"pdf")},
        )
        # 2. Validate the pending structured value before Django saves the parent.
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(File.objects.count(), 0)
        form.save()
        self.assertEqual(len(customer.picture), 1)
        # 3. Required validation still rejects explicitly clearing the field.
        empty = form_class(data={"picture__present": "1"}, instance=customer)
        self.assertFalse(empty.is_valid())
        self.assertIn("picture", empty.errors)

    def test_reference_model_is_internal(self) -> None:
        """
        Use case: The framework discovers the shared file reference model.
        Expected result: It is internal, has no generated API, and produces no separate audit events.
        """
        from bloomerp.models import FileFieldReference
        from bloomerp.models.definition import BloomerpModelConfig
        from bloomerp.services.activity_log_services import ActivityLogManager

        # 1. Validate the model's internal configuration.
        config = FileFieldReference.bloomerp_config
        self.assertIsInstance(config, BloomerpModelConfig)
        self.assertTrue(config.is_internal)
        # 2. Verify API generation and auditing consume the configured settings.
        self.assertFalse(config.should_enable_api_auto_generation())
        self.assertFalse(ActivityLogManager.should_record_change(FileFieldReference))
