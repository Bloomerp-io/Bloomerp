"""Integration checks for reference reconciliation and file access boundaries."""

import json
from typing import Any
from uuid import uuid4

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Model
from django.http import HttpRequest
from django.test import RequestFactory

from bloomerp.files.access import FileAccessManager
from bloomerp.filters.definition import FilterCondition
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import (
    ApplicationField,
    Comment,
    FileNode,
    FileReference,
    Label,
    Mention,
    ObjectLabel,
)
from bloomerp.models.definition import (
    ApiAccessSettings,
    ApiSettings,
    BloomerpModelConfig,
)
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.services.crud_reference_services import prepare_reference_submission
from bloomerp.services.object_reference_services import (
    Reference,
    can_change_label,
    reconcile_references,
    object_reference_state,
    manual_reference_state,
)
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestObjectReferences(BaseBloomerpTestCaseWithModels):
    """Exercise real forms and authorization with dynamically registered model fields."""

    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Create one editable source, its field identity, and a mentionable user."""
        self.customer = self.create_customer("Source", "Object", 30)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.field = ApplicationField.get_by_field(self.CustomerModel, "description")
        self.admin_user.is_staff = True
        self.admin_user.save(update_fields=["is_staff"])

    def request(self, data: dict[str, Any], user: Any = None) -> HttpRequest:
        """Build the same authenticated submission context supplied by CRUD views."""
        request = RequestFactory().post("/", data)
        request.user = user or self.admin_user
        return request

    def mention(self, occurrence: str) -> str:
        """Serialize one user occurrence using the editor's HTML contract."""
        return f'<span data-reference-kind="user" data-target-id="{self.admin_user.pk}" data-occurrence-id="{occurrence}">David</span>'

    def form(self, data: dict[str, Any]) -> Any:
        """Bind an ordinary model form without any reference-specific context."""
        return bloomerp_modelform_factory(self.CustomerModel, fields=["description"])(
            data=data,
            instance=self.customer,
        )

    def payload(
        self, occurrences: list[str], manual: list[dict[str, Any]] | None = None
    ) -> str:
        """Build the explicit occurrence payload that accompanies editor field values."""
        payload: dict[str, Any] = {
            "fields": {
                str(self.field.pk): [
                    {
                        "kind": "user",
                        "target_id": str(self.admin_user.pk),
                        "field_id": self.field.pk,
                        "occurrence_id": occurrence,
                    }
                    for occurrence in occurrences
                ]
            }
        }
        if manual is not None:
            payload["manual"] = manual
        return json.dumps(payload)

    def save_submission(self, data: dict[str, Any], user: Any = None) -> Model:
        """Exercise the independent validation and atomic persistence used by CRUD views."""
        request = self.request(data, user)
        form = self.form(data)
        self.assertTrue(form.is_valid(), form.errors)
        submission = prepare_reference_submission(
            request, form.instance, {"description"}
        )
        with transaction.atomic():
            parent = form.save()
            if submission is not None:
                reconcile_references(
                    parent, submission.fields, submission.manual, request
                )
        return parent

    def test_object_tags_retain_icon_and_navigation_metadata(self) -> None:
        """Keep saved and invalid-form object chips linked to the readable target."""
        from bloomerp.models.project_management.todo import Todo
        from bloomerp.models.definition import get_model_config

        target = Todo.objects.create(title="Linked object tag")
        reference = Reference(
            "object", str(target.pk), ContentType.objects.get_for_model(Todo).pk
        )
        request = self.request({})
        reconcile_references(self.customer, {}, [reference], request)
        for state in (
            object_reference_state(request, self.customer),
            manual_reference_state(request, self.customer, [reference]),
        ):
            chip = state[0]
            self.assertEqual(chip["icon"], get_model_config(Todo).icon)
            self.assertEqual(chip["url"], target.get_absolute_url())

    def test_repeated_mentions_reconcile_independently(self) -> None:
        """Removing one occurrence retains the second mention and explicit attachment."""
        first, second = str(uuid4()), str(uuid4())
        self.save_submission(
            {
                "description": self.mention(first) + self.mention(second),
                "object_references": self.payload(
                    [first, second],
                    [{"kind": "user", "target_id": str(self.admin_user.pk)}],
                ),
            }
        )
        self.assertEqual(Mention.objects.count(), 3)
        self.save_submission(
            {
                "description": self.mention(second),
                "object_references": self.payload([second]),
            }
        )
        self.assertEqual(Mention.objects.count(), 2)
        self.assertTrue(Mention.objects.filter(occurrence_id=second).exists())
        self.assertTrue(Mention.objects.filter(application_field__isnull=True).exists())

    def test_duplicate_occurrence_is_rejected(self) -> None:
        """A duplicated payload identity cannot collapse two chips into one occurrence."""
        occurrence = str(uuid4())
        with self.assertRaises(ValidationError):
            self.save_submission(
                {
                    "description": "Unchanged",
                    "object_references": self.payload([occurrence, occurrence]),
                }
            )
        self.assertEqual(Mention.objects.count(), 0)
        self.customer.refresh_from_db()
        self.assertNotEqual(self.customer.description, "Unchanged")

    def test_inaccessible_target_is_rejected(self) -> None:
        """A forged payload cannot bypass authorization independently of the model form."""
        with self.assertRaises(ValidationError):
            self.save_submission(
                {
                    "description": "Text",
                    "object_references": self.payload([str(uuid4())]),
                },
                self.normal_user,
            )

    def test_model_form_does_not_interpret_reference_markup(self) -> None:
        """Ordinary model forms save their fields without creating reference records."""
        markup = self.mention("not-an-occurrence-uuid")
        form = self.form({"description": markup})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(Mention.objects.count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.description, markup)

    def test_payload_cannot_replace_an_omitted_field(self) -> None:
        """Reference scopes require an editable source field included in the same submission."""
        with self.assertRaises(ValidationError):
            prepare_reference_submission(
                self.request({"object_references": self.payload([])}),
                self.customer,
                {"description"},
            )
        with self.assertRaises(ValidationError):
            prepare_reference_submission(
                self.request(
                    {"description": "Text", "object_references": self.payload([])}
                ),
                self.customer,
                set(),
            )

    def test_omitted_field_preserves_references(self) -> None:
        """Updating another field leaves existing description references intact."""
        reconcile_references(
            self.customer,
            {
                self.field.pk: [
                    Reference(
                        "user",
                        str(self.admin_user.pk),
                        occurrence_id=uuid4(),
                        field_id=self.field.pk,
                    )
                ]
            },
            None,
            self.request({}),
        )
        data = {"first_name": "Changed"}
        form = bloomerp_modelform_factory(self.CustomerModel, fields=["first_name"])(
            data=data, instance=self.customer
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(Mention.objects.count(), 1)

    def test_manual_file_creates_one_reference_without_a_folder(self) -> None:
        """Saving the same attachment repeatedly creates one object usage."""
        file = FileNode.objects.create(
            content=SimpleUploadedFile("attached.txt", b"attachment"),
            kind="FILE",
            created_by=self.admin_user,
        )
        reference = Reference("file", str(file.pk))
        for _ in range(2):
            reconcile_references(self.customer, {}, [reference], self.request({}))
        self.assertEqual(file.references.count(), 1)
        self.assertEqual(file.references.get().object_id, str(self.customer.pk))
        self.assertIsNone(file.parent_id)

    def test_manual_attachment_shares_file_without_changing_other_usages(self) -> None:
        """Two objects can reference the same file; detaching one preserves the other."""
        file = FileNode.objects.create(
            content=SimpleUploadedFile("shared.txt", b"attachment"),
            kind="FILE",
            created_by=self.admin_user,
        )
        reference = Reference("file", str(file.pk))
        other = self.create_customer("Other", "Owner", 31)
        for parent in (self.customer, other):
            reconcile_references(parent, {}, [reference], self.request({}))
        reconcile_references(self.customer, {}, [], self.request({}))
        self.assertEqual(file.references.get().object_id, str(other.pk))
        self.assertTrue(file.content.storage.exists(file.content.name))

    def test_shared_file_survives_field_removal(self) -> None:
        """Clearing one of two rich-text usages preserves shared bytes and the other usage."""
        file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("image.png", b"image"),
            created_by=self.admin_user,
        )
        other = self.create_customer("Other", "Object", 31)
        request = self.request({})
        for parent in [self.customer, other]:
            reconcile_references(
                parent,
                {
                    self.field.pk: [
                        Reference(
                            "file",
                            str(file.pk),
                            occurrence_id=uuid4(),
                            field_id=self.field.pk,
                        )
                    ]
                },
                None,
                request,
            )
        reconcile_references(self.customer, {self.field.pk: []}, None, request)
        self.assertTrue(FileNode.objects.filter(pk=file.pk).exists())
        self.assertEqual(FileReference.objects.filter(file=file).count(), 1)
        self.assertTrue(file.content.storage.exists(file.content.name))

    def test_file_field_removal_preserves_embedded_usage(self) -> None:
        """A dedicated field's former owned file survives when rich text still references it."""
        field = self.CustomerModel._meta.get_field("picture")
        field.on_save(self.customer, [], [SimpleUploadedFile("image.png", b"image")])
        file = self.customer.picture[0]
        reconcile_references(
            self.customer,
            {
                self.field.pk: [
                    Reference(
                        "file",
                        str(file.pk),
                        occurrence_id=uuid4(),
                        field_id=self.field.pk,
                    )
                ]
            },
            None,
            self.request({}),
        )
        field.on_save(self.customer, [], [])
        self.assertTrue(FileNode.objects.filter(pk=file.pk).exists())
        self.assertEqual(file.references.count(), 1)

    def test_unreferenced_upload_requires_owner_or_library_access(self) -> None:
        """Unreferenced uploads require uploader, administrator, or explicit library access."""
        file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("draft.png", b"image"),
            created_by=self.normal_user,
        )
        self.assertTrue(FileAccessManager(self.normal_user).can_read_file_node(file))
        self.assertTrue(FileAccessManager(self.admin_user).can_read_file_node(file))
        self.assertFalse(FileAccessManager(AnonymousUser()).can_read_file_node(file))
        file.created_by = self.admin_user
        file.save(update_fields=["created_by"])
        self.assertFalse(FileAccessManager(self.normal_user).can_read_file_node(file))

    def test_public_file_access_checks_row_and_field(self) -> None:
        """Anonymous bytes require a referencing row and field granted by the same access rule."""
        file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("public.png", b"image"),
        )
        FileReference.objects.create(
            file=file,
            content_object=self.customer,
            application_field=self.field,
            object_id=str(self.customer.pk),
            occurrence_id=uuid4(),
        )
        original = getattr(self.CustomerModel, "bloomerp_config", None)
        try:
            self.CustomerModel.bloomerp_config = BloomerpModelConfig(
                api_settings=ApiSettings(
                    access=ApiAccessSettings(
                        anonymous=[
                            AccessRule(
                                row_permissions=[
                                    RowPolicyRuleContent(
                                        permissions=["view"],
                                        conditions=[
                                            FilterCondition(
                                                field_path="first_name",
                                                lookup_id="equals",
                                                value="Source",
                                            )
                                        ],
                                    )
                                ],
                                field_permissions={"description": ["view"]},
                            )
                        ]
                    )
                )
            )
            self.assertTrue(FileAccessManager(AnonymousUser()).can_read_file_node(file))
            self.customer.first_name = "Private"
            self.customer.save(update_fields=["first_name"])
            self.assertFalse(
                FileAccessManager(AnonymousUser()).can_read_file_node(file)
            )
            self.customer.first_name = "Source"
            self.customer.save(update_fields=["first_name"])
            self.CustomerModel.bloomerp_config.api_settings.access.anonymous[
                0
            ].field_permissions = {"first_name": ["view"]}
            self.assertFalse(
                FileAccessManager(AnonymousUser()).can_read_file_node(file)
            )
        finally:
            if original is None:
                del self.CustomerModel.bloomerp_config
            else:
                self.CustomerModel.bloomerp_config = original

    def test_labels_are_unique_and_creator_managed(self) -> None:
        """Label names normalize whitespace/case and editing stays with creator or admin."""
        label = Label.objects.create(name=" Urgent ", created_by=self.normal_user)
        self.assertEqual(label.name, "Urgent")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Label.objects.create(name="urgent")
        self.assertTrue(can_change_label(self.normal_user, label))
        self.assertTrue(can_change_label(self.admin_user, label))
        label.created_by = self.admin_user
        self.assertFalse(can_change_label(self.normal_user, label))
        ObjectLabel.objects.create(
            content_type=self.content_type, object_id=str(self.customer.pk), label=label
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ObjectLabel.objects.create(
                content_type=self.content_type,
                object_id=str(self.customer.pk),
                label=label,
            )

    def test_comment_mentions_do_not_attach_to_parent(self) -> None:
        """Comment-owned occurrences remain outside the parent's reference collection."""
        comment = Comment.objects.create(
            content_object=self.customer, content="Hello", created_by=self.admin_user
        )
        field = ApplicationField.get_by_field(Comment, "content")
        reconcile_references(
            comment,
            {
                field.pk: [
                    Reference(
                        "user",
                        str(self.admin_user.pk),
                        occurrence_id=uuid4(),
                        field_id=field.pk,
                    )
                ]
            },
            None,
            self.request({}),
        )
        self.assertEqual(
            Mention.objects.filter(
                content_type=ContentType.objects.get_for_model(Comment),
                object_id=str(comment.pk),
            ).count(),
            1,
        )
        self.assertFalse(
            Mention.objects.filter(
                content_type=self.content_type, object_id=str(self.customer.pk)
            ).exists()
        )

    def test_parent_deletion_removes_links_without_deleting_shared_file(self) -> None:
        """Deleting the source clears mentions and field usage while retaining reusable bytes."""
        file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("shared.png", b"image"),
        )
        reconcile_references(
            self.customer,
            {
                self.field.pk: [
                    Reference(
                        "file",
                        str(file.pk),
                        occurrence_id=uuid4(),
                        field_id=self.field.pk,
                    ),
                    Reference(
                        "user",
                        str(self.admin_user.pk),
                        occurrence_id=uuid4(),
                        field_id=self.field.pk,
                    ),
                ]
            },
            None,
            self.request({}),
        )
        self.customer.delete()
        self.assertEqual(Mention.objects.count(), 0)
        self.assertEqual(FileReference.objects.count(), 0)
        self.assertTrue(FileNode.objects.filter(pk=file.pk).exists())

    def test_validation_failure_does_not_attach_upload(self) -> None:
        """A forged occurrence leaves the upload unreferenced and the parent unchanged."""
        file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("draft.png", b"image"),
            created_by=self.admin_user,
        )
        payload = {
            "fields": {
                str(self.field.pk): [
                    {
                        "kind": "file",
                        "target_id": str(file.pk),
                        "field_id": self.field.pk,
                        "occurrence_id": "invalid",
                    }
                ]
            }
        }
        with self.assertRaises(ValidationError):
            self.save_submission(
                {"description": "Image", "object_references": json.dumps(payload)}
            )
        file.refresh_from_db()
        self.assertFalse(file.references.exists())
