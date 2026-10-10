from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.test import RequestFactory

from bloomerp.files.access import FileAccessManager
from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    FileNode,
    FileReference,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestFileFieldPermissions(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

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
