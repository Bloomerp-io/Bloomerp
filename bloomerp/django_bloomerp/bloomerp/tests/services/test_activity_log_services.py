import uuid

from bloomerp.models.activity_log import ActivityLog, ActivityLogAction
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.serializers.model_serializers import set_serializer_cls
from bloomerp.services.activity_log_services import ActivityLogManager
from bloomerp.tests.base import BaseBloomerpModelTestCase


class ActivityLogManagerTestCase(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def extendedSetup(self):
        if hasattr(self.CustomerModel, "bloomerp_config"):
            delattr(self.CustomerModel, "bloomerp_config")
        self.customer = self.create_customer("Ada", "Lovelace", 28)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(record_activity_log=True)
        set_serializer_cls(self.CustomerModel)

    def test_build_changes_converts_uuid_values_to_json_safe_strings(self):
        manager = ActivityLogManager(self.customer)
        related_id = uuid.uuid4()

        changes = manager._build_changes(
            before_data={"country": None},
            after_data={"country": related_id},
        )

        self.assertEqual(
            changes,
            [
                {
                    "field": "country",
                    "from": None,
                    "to": str(related_id),
                }
            ],
        )

    def test_persist_accepts_uuid_values_in_payload(self):
        manager = ActivityLogManager(self.customer)
        related_id = uuid.uuid4()
        manager.payload = [
            {
                "field": "country",
                "from": None,
                "to": related_id,
            }
        ]

        activity_log = manager.persist()

        self.assertEqual(ActivityLog.objects.count(), 1)
        self.assertEqual(activity_log.payload[0]["to"], str(related_id))

    def test_persist_skips_empty_change_payloads(self):
        manager = ActivityLogManager(self.customer)
        manager.payload = []

        activity_log = manager.persist()

        self.assertIsNone(activity_log)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_delete_signal_stores_full_object_payload_after_delete(self):
        customer_id = str(self.customer.pk)

        self.customer.delete()

        activity_log = ActivityLog.objects.get(object_id=customer_id)
        self.assertEqual(activity_log.action, ActivityLogAction.DELETE)
        self.assertEqual(activity_log.payload["id"], customer_id)
        self.assertEqual(activity_log.payload["first_name"], "Ada")
        self.assertEqual(activity_log.payload["last_name"], "Lovelace")

    def test_summary_string_handles_payload_field_key_and_missing_field_names(self):
        activity_log = ActivityLog.objects.create(
            content_type=ActivityLogManager(self.customer).get_content_type(),
            object_id=str(self.customer.pk),
            payload=[
                {"field": "department", "from": None, "to": "Finance"},
                {"field_name": None, "from": None, "to": None},
            ],
        )

        self.assertEqual(
            activity_log.summary_string,
            "System changed the field department to Finance",
        )

    def test_summary_string_lists_two_changed_fields(self):
        activity_log = ActivityLog.objects.create(
            content_type=ActivityLogManager(self.customer).get_content_type(),
            object_id=str(self.customer.pk),
            payload=[
                {"field": "first_name", "from": "Ada", "to": "Grace"},
                {"field": "last_name", "from": "Lovelace", "to": "Hopper"},
            ],
        )

        self.assertEqual(
            activity_log.summary_string,
            "System changed the fields first_name and last_name",
        )

    def test_summary_string_summarizes_more_than_two_changed_fields(self):
        activity_log = ActivityLog.objects.create(
            content_type=ActivityLogManager(self.customer).get_content_type(),
            object_id=str(self.customer.pk),
            payload=[
                {"field": "first_name", "from": "Ada", "to": "Grace"},
                {"field": "last_name", "from": "Lovelace", "to": "Hopper"},
                {"field": "age", "from": 28, "to": 85},
            ],
        )

        self.assertEqual(
            activity_log.summary_string,
            "System changed the fields first_name, last_name and more",
        )
