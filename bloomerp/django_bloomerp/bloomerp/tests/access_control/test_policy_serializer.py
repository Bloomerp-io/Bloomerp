from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.access_control.row_policy_rule import RowPolicyRuleContent
from bloomerp.serializers.access_control import PolicySerializer
from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestPolicySerializer(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def extendedSetup(self):
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.first_name_field = ApplicationField.objects.get(
            content_type=self.content_type,
            field="first_name",
        )
        self._ensure_permission("view")
        self._ensure_permission("change")

    def _ensure_permission(self, action: str) -> Permission:
        permission, _ = Permission.objects.get_or_create(
            codename=f"{action}_{self.CustomerModel._meta.model_name}",
            content_type=self.content_type,
            defaults={"name": f"Can {action} {self.CustomerModel._meta.verbose_name}"},
        )
        return permission

    def build_payload(self, global_permissions, row_permissions, field_permissions):
        return {
            "name": "Customer policy",
            "description": "Serializer test",
            "content_type_id": self.content_type.id,
            "global_permissions": global_permissions,
            "row_policy": {
                "name": "Customer row policy",
                "rules": [
                    {
                        "rule": {
                            "connector": "OR",
                            "conditions": [
                                {
                                    "application_field_id": str(self.first_name_field.pk),
                                    "operator": "exact",
                                    "value": "Alice",
                                }
                            ],
                        },
                        "permissions": row_permissions,
                    }
                ],
            },
            "field_policy": {
                "name": "Customer field policy",
                "rules": {
                    str(self.first_name_field.pk): field_permissions,
                },
            },
        }

    def test_serializer_accepts_row_and_field_permissions_with_matching_global_permissions(self):
        payload = self.build_payload(
            global_permissions=["view_customer", "change_customer"],
            row_permissions=["view_customer"],
            field_permissions=["change_customer"],
        )

        serializer = PolicySerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_serializer_rejects_permissions_not_present_in_global_permissions(self):
        payload = self.build_payload(
            global_permissions=["view_customer"],
            row_permissions=["change_customer"],
            field_permissions=["change_customer"],
        )

        serializer = PolicySerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("row_policy", serializer.errors)
        self.assertIn("field_policy", serializer.errors)

    def test_serializer_updates_existing_policy_in_place(self):
        create_payload = self.build_payload(
            global_permissions=["view_customer", "change_customer"],
            row_permissions=["view_customer"],
            field_permissions=["change_customer"],
        )
        create_serializer = PolicySerializer(data=create_payload)
        self.assertTrue(create_serializer.is_valid(), create_serializer.errors)
        policy = create_serializer.save()

        original_row_policy_id = policy.row_policy_id
        original_field_policy_id = policy.field_policy_id

        updated_payload = self.build_payload(
            global_permissions=["change_customer"],
            row_permissions=["change_customer"],
            field_permissions=["change_customer"],
        )
        updated_payload["name"] = "Updated customer policy"
        updated_payload["description"] = "Updated serializer test"
        updated_payload["row_policy"]["name"] = "Updated row policy"
        updated_payload["field_policy"]["name"] = "Updated field policy"
        updated_payload["row_policy"]["rules"][0]["rule"]["conditions"][0]["value"] = "Bob"

        update_serializer = PolicySerializer(instance=policy, data=updated_payload)
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        updated_policy = update_serializer.save()

        self.assertEqual(updated_policy.pk, policy.pk)
        self.assertEqual(updated_policy.row_policy_id, original_row_policy_id)
        self.assertEqual(updated_policy.field_policy_id, original_field_policy_id)
        self.assertEqual(updated_policy.name, "Updated customer policy")
        self.assertEqual(updated_policy.description, "Updated serializer test")
        self.assertEqual(
            list(updated_policy.global_permissions.values_list("codename", flat=True)),
            ["change_customer"],
        )
        self.assertEqual(updated_policy.row_policy.name, "Updated row policy")
        self.assertEqual(updated_policy.field_policy.name, "Updated field policy")
        self.assertEqual(updated_policy.row_policy.rules.count(), 1)
        self.assertEqual(updated_policy.row_policy.rules.first().rule["conditions"][0]["value"], "Bob")
        self.assertEqual(
            list(updated_policy.row_policy.rules.first().permissions.values_list("codename", flat=True)),
            ["change_customer"],
        )
        self.assertEqual(
            updated_policy.field_policy.rule,
            {str(self.first_name_field.pk): ["change_customer"]},
        )

    def test_serializer_accepts_and_rule_with_multiple_conditions(self):
        payload = self.build_payload(
            global_permissions=["view_customer"],
            row_permissions=["view_customer"],
            field_permissions=["view_customer"],
        )
        payload["row_policy"]["rules"][0]["rule"] = {
            "connector": "AND",
            "conditions": [
                {
                    "application_field_id": str(self.first_name_field.pk),
                    "operator": "exact",
                    "value": "Alice",
                },
                {
                    "application_field_id": str(self.first_name_field.pk),
                    "operator": "icontains",
                    "value": "Ali",
                },
            ],
        }

        serializer = PolicySerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_serializer_accepts_all_rule_without_operator_or_value(self):
        payload = self.build_payload(
            global_permissions=["view_customer"],
            row_permissions=["view_customer"],
            field_permissions=["view_customer"],
        )
        payload["row_policy"]["rules"][0]["rule"] = {
            "connector": "OR",
            "conditions": [
                {
                    "field": "__all__",
                }
            ],
        }

        serializer = PolicySerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_row_policy_rule_content_requires_condition_details_except_all(self):
        required_rule_parts = [
            {
                "operator": "exact",
                "value": "Alice",
            },
            {
                "application_field_id": str(self.first_name_field.pk),
                "value": "Alice",
            },
            {
                "application_field_id": str(self.first_name_field.pk),
                "operator": "exact",
            },
        ]

        for condition in required_rule_parts:
            with self.subTest(condition=condition):
                with self.assertRaises(ValueError):
                    RowPolicyRuleContent.model_validate(
                        {
                            "connector": "OR",
                            "conditions": [condition],
                        }
                    )

    def test_serializer_rejects_old_flat_row_rule_shape(self):
        payload = self.build_payload(
            global_permissions=["view_customer"],
            row_permissions=["view_customer"],
            field_permissions=["view_customer"],
        )
        payload["row_policy"]["rules"][0]["rule"] = {
            "application_field_id": str(self.first_name_field.pk),
            "operator": "exact",
            "value": "Alice",
        }

        serializer = PolicySerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("row_policy", serializer.errors)
