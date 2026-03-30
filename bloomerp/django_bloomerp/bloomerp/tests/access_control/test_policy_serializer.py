from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from bloomerp.models.application_field import ApplicationField
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
                            "application_field_id": str(self.first_name_field.pk),
                            "operator": "exact",
                            "value": "Alice",
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
