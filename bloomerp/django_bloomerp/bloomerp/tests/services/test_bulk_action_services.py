from typing import Any, ClassVar

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

from bloomerp.filters.definition import FilterCondition
from bloomerp.lookups import builtins as lookups
from bloomerp.model_fields.address_field import AddressField
from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.permissions.definition import (
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import ensure_model_permissions
from bloomerp.services.bulk_action_services import BulkActionService
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models


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


class TestBulkAddressUpdateService(BaseBloomerpTestCaseWithModels):
    """Exercise structured bulk updates through real model forms and persistence."""

    auto_create_customers = False
    original_address: ClassVar[dict[str, str]] = {
        "street_1": "Old street 1",
        "street_2": "",
        "postal_code": "1000",
        "city": "Brussels",
        "state": "",
        "country": "BE",
    }
    replacement_address: ClassVar[dict[str, str]] = {
        "street_1": "New street 2",
        "street_2": "Suite 3",
        "postal_code": "1012",
        "city": "Amsterdam",
        "state": "North Holland",
        "country": "NL",
    }

    @classmethod
    def setUpClass(cls) -> None:
        """Create isolated models covering addresses and ordinary relation fields."""
        super().setUpClass()
        test_models = create_test_models(
            app_label="bloomerp",
            model_defs={
                "BulkAddressTag": {
                    "name": models.CharField(max_length=100),
                },
                "BulkAddressRecord": {
                    "name": models.CharField(max_length=100),
                    "address": AddressField(blank=True, null=True),
                    "primary_tag": models.ForeignKey(
                        "BulkAddressTag",
                        on_delete=models.SET_NULL,
                        blank=True,
                        null=True,
                        related_name="primary_records",
                    ),
                    "tags": models.ManyToManyField("BulkAddressTag", blank=True),
                },
            },
            use_bloomerp_base=True,
        )
        cls.AddressModel = test_models["BulkAddressRecord"]
        cls.TagModel = test_models["BulkAddressTag"]

    def create_address_record(self, name: str) -> models.Model:
        """Create a record with an existing address so accidental clearing is visible."""
        return self.AddressModel.objects.create(
            name=name,
            address=dict(self.original_address),
        )

    def update_records(
        self,
        records: list[models.Model],
        value: Any,
        field_name: str = "address",
        normal_user: bool = False,
    ) -> int:
        """Invoke the public bulk service with serialized object identifiers."""
        return BulkActionService(
            model=self.AddressModel,
            user=self.normal_user if normal_user else self.admin_user,
        ).update_field(
            application_field=ApplicationField.get_by_field(
                self.AddressModel, field_name
            ),
            object_ids=[str(record.pk) for record in records],
            value=value,
        )

    def grant_address_policy(self, allow_field: bool = True) -> None:
        """Allow bulk changes only to named permitted rows, optionally granting the field."""
        content_type = ContentType.objects.get_for_model(self.AddressModel)
        ensure_model_permissions(self.AddressModel)
        bulk_permission = f"bulk_change_{self.AddressModel._meta.model_name}"
        change_permission = f"change_{self.AddressModel._meta.model_name}"
        self.normal_user.user_permissions.add(
            *Permission.objects.filter(
                content_type=content_type,
                codename__in=[bulk_permission, change_permission],
            )
        )
        row_policy = RowPolicy.objects.create(
            content_type=content_type, name="Bulk address rows"
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    FilterCondition(
                        field_path="name",
                        lookup_id=lookups.EQUALS.id,
                        value="Permitted",
                    )
                ],
            ).model_dump(),
        )
        row_rule.add_permission(bulk_permission)
        address_field = ApplicationField.get_by_field(self.AddressModel, "address")
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name="Bulk address fields",
            rule={str(address_field.pk): [change_permission]} if allow_field else {},
        )
        Policy.objects.create(
            name="Bulk address policy",
            row_policy=row_policy,
            field_policy=field_policy,
        ).assign_user(self.normal_user)

    def test_mapping_updates_every_selected_address_and_preserves_unselected(self) -> None:
        """A mapping must persist all components on selected rows without clearing others."""
        selected = [self.create_address_record("First"), self.create_address_record("Second")]
        unselected = self.create_address_record("Unselected")

        self.assertEqual(self.update_records(selected, dict(self.replacement_address)), 2)

        for record in selected:
            record.refresh_from_db()
            self.assertEqual(record.address, self.replacement_address)
        unselected.refresh_from_db()
        self.assertEqual(unselected.address, self.original_address)

    def test_component_list_updates_address_in_widget_order(self) -> None:
        """A cleaned component list must bind to the address widget's subfields."""
        record = self.create_address_record("List input")
        components = ["New street 2", "Suite 3", "1012", "Amsterdam", "North Holland", "NL"]

        self.assertEqual(self.update_records([record], components), 1)

        record.refresh_from_db()
        self.assertEqual(record.address, self.replacement_address)

    def test_none_clears_optional_address(self) -> None:
        """An explicit empty value must clear an optional address and report the update."""
        record = self.create_address_record("Clear input")

        self.assertEqual(self.update_records([record], None), 1)

        record.refresh_from_db()
        self.assertIsNone(record.address)

    def test_invalid_country_raises_and_preserves_existing_address(self) -> None:
        """Invalid country input must fail form validation instead of silently clearing."""
        record = self.create_address_record("Invalid country")
        invalid = {**self.replacement_address, "country": "INVALID"}

        with self.assertRaises(ValidationError):
            self.update_records([record], invalid)

        record.refresh_from_db()
        self.assertEqual(record.address, self.original_address)

    def test_bulk_update_requires_global_permission(self) -> None:
        """An unprivileged user cannot mutate a selected address."""
        record = self.create_address_record("Permitted")

        with self.assertRaises(PermissionDenied):
            self.update_records([record], self.replacement_address, normal_user=True)

        record.refresh_from_db()
        self.assertEqual(record.address, self.original_address)

    def test_bulk_update_requires_field_change_permission(self) -> None:
        """Global bulk permission cannot bypass a missing address field grant."""
        record = self.create_address_record("Permitted")
        self.grant_address_policy(allow_field=False)

        with self.assertRaises(PermissionDenied):
            self.update_records([record], self.replacement_address, normal_user=True)

        record.refresh_from_db()
        self.assertEqual(record.address, self.original_address)

    def test_bulk_update_respects_row_policy(self) -> None:
        """Only selected rows matched by the user's bulk-change policy are changed."""
        permitted = self.create_address_record("Permitted")
        protected = self.create_address_record("Protected")
        self.grant_address_policy()

        count = self.update_records(
            [permitted, protected], self.replacement_address, normal_user=True
        )

        self.assertEqual(count, 1)
        permitted.refresh_from_db()
        protected.refresh_from_db()
        self.assertEqual(permitted.address, self.replacement_address)
        self.assertEqual(protected.address, self.original_address)

    def test_scalar_update_retains_ordinary_form_binding(self) -> None:
        """Scalar fields must remain bound directly while structured fields are supported."""
        record = self.create_address_record("Before")

        self.assertEqual(self.update_records([record], "After", field_name="name"), 1)

        record.refresh_from_db()
        self.assertEqual(record.name, "After")
        self.assertEqual(record.address, self.original_address)

    def test_foreign_key_update_retains_ordinary_form_binding(self) -> None:
        """Foreign keys must still accept serialized related-object identifiers."""
        record = self.create_address_record("Relation")
        tag = self.TagModel.objects.create(name="Primary")

        self.assertEqual(
            self.update_records([record], str(tag.pk), field_name="primary_tag"), 1
        )

        record.refresh_from_db()
        self.assertEqual(record.primary_tag_id, tag.pk)
        self.assertEqual(record.address, self.original_address)

    def test_many_to_many_list_is_not_expanded_as_a_multiwidget(self) -> None:
        """Relation lists must remain intact for model multiple-choice validation and saving."""
        record = self.create_address_record("Relations")
        first = self.TagModel.objects.create(name="First")
        second = self.TagModel.objects.create(name="Second")

        self.assertEqual(
            self.update_records([record], [str(first.pk), str(second.pk)], field_name="tags"),
            1,
        )

        self.assertSetEqual(set(record.tags.values_list("pk", flat=True)), {first.pk, second.pk})
        record.refresh_from_db()
        self.assertEqual(record.address, self.original_address)
