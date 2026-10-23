from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from bloomerp.files.access import FileAccessManager
from bloomerp.models import (
    ApplicationField,
    Comment,
    FieldPolicy,
    FileNode,
    FileReference,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFileFieldPermissions(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def test_file_collections_respect_model_base_filter(self) -> None:
        """
        Use case: A file collection excludes an otherwise readable attachment.
        Expected result: Its base filter applies to both admins and ordinary users.
        """
        # 1. Grant both attachments and restrict the model to the generic file.
        self.grant_field("files")
        self.grant_field("picture")
        base_filter = Filter(connector="AND", conditions=[
            FilterCondition(
                field_path="id", lookup_id="equals", value=str(self.generic_file.pk)
            )
        ])

        # 2. Resolve the specialized file scope for each caller with the same filter.
        with patch.object(FileNode.bloomerp_config, "base_filter", base_filter):
            for user in (self.admin_user, self.normal_user):
                with self.subTest(superuser=user.is_superuser):
                    self.assertEqual(
                        list(FileAccessManager(user).get_queryset(FileNode.objects.all())),
                        [self.generic_file],
                    )
                    self.assertFalse(
                        FileAccessManager(user).can_mutate_file_node(self.picture_file)
                    )

    def extendedSetup(self) -> None:
        """Create a field-owned attachment and a generic object attachment."""
        self.customer = self.create_customer("Private", "Customer", 30)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.CustomerModel._meta.get_field("picture").on_save(
            self.customer, [], [SimpleUploadedFile("picture.pdf", b"pdf")]
        )
        self.picture_file = FileNode.objects.get(pk=self.customer.picture[0].pk)
        self.generic_file = FileNode.objects.create(
            kind="FILE",
            content=SimpleUploadedFile("generic.pdf", b"pdf"),
        )

        FileReference.objects.create(
            file=self.generic_file, content_object=self.customer
        )

    def request_for(self, *, admin: bool = False) -> HttpRequest:
        """Build a request for either the ordinary user or superuser."""
        request = RequestFactory().get("/")
        request.user = self.admin_user if admin else self.normal_user
        return request

    def grant_field(self, field_name: str) -> None:
        """Grant object viewing and all tested operations on one specific field."""
        permissions = list(
            Permission.objects.filter(
                content_type=self.content_type,
                codename__in=["view_customer", "change_customer", "delete_customer"],
            )
        )
        application_field = ApplicationField.get_by_field(
            self.CustomerModel, field_name
        )
        row_policy = RowPolicy.objects.create(
            name="View object", content_type=self.content_type
        )
        rule = RowPolicyRule.objects.create(
            row_policy=row_policy, rule={"connector": "AND", "conditions": []}
        )
        rule.permissions.add(*permissions)
        field_policy = FieldPolicy.objects.create(
            name="Access one attachment field",
            content_type=self.content_type,
            rule={
                str(application_field.pk): [
                    permission.codename for permission in permissions
                ]
            },
        )
        policy = Policy.objects.create(
            name="Attachment access", row_policy=row_policy, field_policy=field_policy
        )
        policy.global_permissions.add(*permissions)
        policy.users.add(self.normal_user)

    def test_attachment_requires_its_own_field_permission(self) -> None:
        """
        Use case: A user can view generic files but cannot view the picture field.
        Expected result: Generic files are accessible while the field attachment is hidden.
        """
        # 1. Grant access to the generic files field.
        self.grant_field("files")
        request = self.request_for()
        # 2. Verify field-owned attachments do not inherit generic files access.
        self.assertTrue(
            FileAccessManager(request.user).can_read_file_node(self.generic_file)
        )
        self.assertFalse(
            FileAccessManager(request.user).can_read_file_node(self.picture_file)
        )

    def test_specific_field_grants_attachment_access(self) -> None:
        """
        Use case: A user has permissions for the owning picture field only.
        Expected result: That attachment is viewable; generic files remain hidden.
        """
        # 1. Grant access to the field owning the attachment.
        self.grant_field("picture")
        request = self.request_for()
        # 2. Verify attachment access follows the owning field.
        self.assertTrue(
            FileAccessManager(request.user).can_read_file_node(self.picture_file)
        )
        self.assertFalse(
            FileAccessManager(request.user).can_read_file_node(self.generic_file)
        )

    def test_no_policy_and_superuser_behavior(self) -> None:
        """
        Use case: An ordinary user has no grants and an administrator opens the file.
        Expected result: The ordinary user is denied and the superuser retains access.
        """
        # 1. Verify the ordinary user's default denial.
        self.assertFalse(
            FileAccessManager(self.request_for().user).can_read_file_node(
                self.picture_file
            )
        )
        # 2. Verify the administrator's existing bypass.
        self.assertTrue(
            FileAccessManager(self.request_for(admin=True).user).can_read_file_node(
                self.picture_file
            )
        )

    def test_read_queryset_query_count_does_not_grow_with_files(self) -> None:
        """
        Use case: Many files reference the same readable owner field.
        Expected result: Query count stays bounded when filtering one or thirty files.
        """
        # 1. Attach a growing collection to one permitted owner.
        self.grant_field("files")
        ids = [self.generic_file.pk]
        for index in range(29):
            file = FileNode.objects.create(
                name=f"Batch-{index}", kind="FILE",
                content=SimpleUploadedFile(f"batch-{index}.pdf", b"pdf"),
            )
            FileReference.objects.create(file=file, content_object=self.customer)
            ids.append(file.pk)
        # 2. Count the entire permission resolution and file retrieval.
        counts: list[int] = []
        for size in (1, 30):
            with CaptureQueriesContext(connection) as captured:
                files = list(FileAccessManager(self.normal_user).get_queryset(
                    FileNode.objects.filter(pk__in=ids[:size])
                ))
            self.assertEqual(len(files), size)
            counts.append(len(captured))
        # Django may populate authentication/content-type caches on the first call.
        self.assertLessEqual(counts[1], counts[0])
        self.assertLessEqual(counts[1], 10)

    def test_read_queryset_preserves_row_field_and_shared_reference_scope(self) -> None:
        """
        Use case: A file has both private and public owners with different field grants.
        Expected result: One matching row/field grant permits the file without widening scope.
        """
        # 1. Allow only one customer's generic attachments through a group policy.
        visible = self.create_customer("Visible", "Customer", 30)
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={"files": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[
                FilterCondition(field_path="first_name", lookup_id="equals", value="Visible")
            ])],
        )
        group = Group.objects.create(name="File readers")
        group.user_set.add(self.normal_user)
        policy.groups.add(group)
        # 2. A private reference does not let the uploader bypass reference permissions.
        self.generic_file.created_by = self.normal_user
        self.generic_file.save(update_fields=["created_by"])
        access = FileAccessManager(self.normal_user)
        self.assertFalse(access.get_queryset(FileNode.objects.all()).exists())
        # 3. Sharing through a readable reference grants the file once, retaining input scope.
        FileReference.objects.create(file=self.generic_file, content_object=visible)
        self.assertEqual(list(access.get_queryset(FileNode.objects.all())), [self.generic_file])
        self.assertFalse(access.get_queryset(FileNode.objects.filter(pk=self.picture_file.pk)).exists())
        self.assertEqual(list(access.get_queryset(FileNode.objects.all(), related_object=visible)), [self.generic_file])

    def test_comment_attachment_uses_parent_comments_permission(self) -> None:
        """
        Use case: An embedded comment file inherits its parent's comments field access.
        Expected result: Parent files access alone denies it; comments access grants it.
        """
        # 1. Attach the file to a comment's rich-text content.
        comment = Comment.objects.create(content_object=self.customer, content="Attachment")
        field = ApplicationField.get_by_field(Comment, "content")
        FileReference.objects.create(
            file=self.generic_file, content_object=comment,
            application_field=field, occurrence_id=uuid4(),
        )
        FileReference.objects.filter(file=self.generic_file, application_field__isnull=True).delete()
        # 2. Verify permissions follow the parent comments field rather than generic files.
        self.grant_field("files")
        self.assertFalse(FileAccessManager(self.normal_user).can_read_file_node(self.generic_file))
        self.grant_field("comments")
        self.assertTrue(FileAccessManager(self.normal_user).can_read_file_node(self.generic_file))

    def test_uuid_reference_owner_is_resolved_in_sql(self) -> None:
        """
        Use case: A readable file is attached to a UUID-keyed task.
        Expected result: Generic string IDs match UUID database keys correctly.
        """
        # 1. Give the user field and row access to task attachments.
        todo = Todo.objects.create(title="UUID attachment owner")
        policy = PolicyManager.create_policy(
            model_or_content_type=Todo, field_permissions={"files": ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)
        # 2. Permit the shared file through its task reference.
        FileReference.objects.create(file=self.generic_file, content_object=todo)
        self.assertTrue(FileAccessManager(self.normal_user).can_read_file_node(self.generic_file))

    def test_unreferenced_scope_and_bulk_upload_privacy(self) -> None:
        """
        Use case: Upload owners and library readers browse unused files and import sources.
        Expected result: Library access never bypasses reference rules or import privacy.
        """
        # 1. Create unused uploads for both users, plus a private import source and folder.
        owned = FileNode.objects.create(
            kind="FILE", content=SimpleUploadedFile("owned.pdf", b"pdf"),
            created_by=self.normal_user,
        )
        other = FileNode.objects.create(
            kind="FILE", content=SimpleUploadedFile("other.pdf", b"pdf"),
            created_by=self.admin_user,
        )
        source = FileNode.objects.create(
            kind="FILE", content=SimpleUploadedFile("source.csv", b"csv"),
            created_by=self.normal_user,
            meta={"bulk_upload": {
                "content_type_id": self.content_type.pk,
                "model_label": self.CustomerModel._meta.label,
                "original_filename": "source.csv",
            }},
        )
        FileNode.objects.create(kind="FOLDER", name="Folder")
        # 2. An uploader sees only their unused file; library access adds other unused files.
        self.assertEqual(list(FileAccessManager(self.normal_user).get_queryset(FileNode.objects.all())), [owned])
        permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(FileNode), codename="view_filenode"
        )
        self.normal_user.user_permissions.add(permission)
        self.normal_user = type(self.normal_user).objects.get(pk=self.normal_user.pk)
        self.assertEqual(set(FileAccessManager(self.normal_user).get_queryset(FileNode.objects.all())), {owned, other})
        # 3. Even administrators cannot read an import source or folder as a file.
        files = set(FileAccessManager(self.admin_user).get_queryset(FileNode.objects.all()))
        self.assertNotIn(source, files)
        self.assertEqual(files, {owned, other, self.generic_file, self.picture_file})
