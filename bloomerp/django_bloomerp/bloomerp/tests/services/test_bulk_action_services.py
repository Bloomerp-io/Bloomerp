from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied

from bloomerp.lookups import builtins as lookups
from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.models.access_control.row_policy_rule import (
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.services.bulk_action_services import BulkActionService
from bloomerp.permissions.manager import ensure_model_permissions
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class TestBulkActionService(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def test_delete_objects_deletes_only_requested_objects(self):
        """
        Use case: A permitted user bulk deletes a selected collection of objects.
        Expected result: Only the requested objects are deleted.
        """
        # 1. Create selected and unselected objects.
        selected = self.create_customer("Selected", "Customer", 30)
        unselected = self.create_customer("Unselected", "Customer", 31)

        # 2. Delete the selected object as a superuser.
        deleted_count = BulkActionService(
            model=self.CustomerModel,
            user=self.admin_user,
        ).delete_objects(object_ids=[str(selected.pk)])

        # 3. Confirm only the selected object was deleted.
        self.assertEqual(deleted_count, 1)
        self.assertFalse(self.CustomerModel.objects.filter(pk=selected.pk).exists())
        self.assertTrue(self.CustomerModel.objects.filter(pk=unselected.pk).exists())

    def test_delete_objects_requires_bulk_delete_permission(self):
        """
        Use case: A user without bulk-delete permission requests a bulk deletion.
        Expected result: The service denies the deletion and preserves the object.
        """
        # 1. Create an object for a normal user to attempt to delete.
        customer = self.create_customer("Protected", "Customer", 30)

        # 2. Attempt the deletion without a matching policy or permission.
        with self.assertRaises(PermissionDenied):
            BulkActionService(
                model=self.CustomerModel,
                user=self.normal_user,
            ).delete_objects(object_ids=[str(customer.pk)])

        # 3. Confirm the protected object remains.
        self.assertTrue(self.CustomerModel.objects.filter(pk=customer.pk).exists())

    def test_delete_objects_respects_bulk_delete_row_policy(self):
        """
        Use case: A user can bulk delete only rows matched by their delete policy.
        Expected result: Requested objects outside the row policy remain untouched.
        """
        # 1. Create one permitted and one protected object.
        permitted = self.create_customer("Permitted", "Customer", 30)
        protected = self.create_customer("Protected", "Customer", 31)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        ensure_model_permissions(self.CustomerModel)
        bulk_delete_permission = Permission.objects.get(
            content_type=content_type,
            codename="bulk_delete_customer",
        )
        self.normal_user.user_permissions.add(bulk_delete_permission)

        # 2. Grant row-level bulk delete access only to the permitted object.
        first_name_field = ApplicationField.get_by_field(
            self.CustomerModel,
            "first_name",
        )
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name="Selected customer deletion",
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(first_name_field.pk),
                        operator=lookups.EQUALS.id,
                        value=permitted.first_name,
                    ),
                ],
            ).model_dump(),
        )
        row_rule.add_permission("bulk_delete_customer")
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name="Selected customer deletion",
            rule={},
        )
        policy = Policy.objects.create(
            name="Selected customer deletion",
            description="Allows bulk deletion of matching customers.",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(self.normal_user)

        # 3. Request deletion of both objects.
        deleted_count = BulkActionService(
            model=self.CustomerModel,
            user=self.normal_user,
        ).delete_objects(
            object_ids=[str(permitted.pk), str(protected.pk)],
        )

        # 4. Confirm the row policy limited the deletion.
        self.assertEqual(deleted_count, 1)
        self.assertFalse(self.CustomerModel.objects.filter(pk=permitted.pk).exists())
        self.assertTrue(self.CustomerModel.objects.filter(pk=protected.pk).exists())
