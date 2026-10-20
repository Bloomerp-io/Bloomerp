import uuid
from types import SimpleNamespace

from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction
from bloomerp.models.definition import ActivityLogSettings, BloomerpModelConfig
from bloomerp.serializers.model_serializers import (
    _model_serializers,
    get_serializer_cls,
    set_serializer_cls,
)
from bloomerp.services.activity_log_services import ActivityLogManager
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class ActivityLogManagerTestCase(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def extendedSetup(self):
        if hasattr(self.CustomerModel, "bloomerp_config"):
            delattr(self.CustomerModel, "bloomerp_config")
        self.customer = self.create_customer("Ada", "Lovelace", 28)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(activity_log_settings=ActivityLogSettings(enabled=True))
        set_serializer_cls(self.CustomerModel)
        ActivityLog.objects.all().delete()

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

    def test_activity_log_model_does_not_record_activity_logs_for_itself(self):
        ActivityLog.objects.create(
            content_type=ActivityLogManager(self.customer).get_content_type(),
            object_id=str(self.customer.pk),
            payload=[],
        )

        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_persist_skips_empty_change_payloads(self):
        manager = ActivityLogManager(self.customer)
        manager.payload = []

        activity_log = manager.persist()

        self.assertIsNone(activity_log)
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_set_changes_preserves_created_by_when_updating(self):
        """
        Use case: A different authenticated user updates an existing object.
        Expected result: The creator is preserved and only updated_by changes.
        """
        # 1. Save the original creator on an existing object.
        self.customer.created_by = self.admin_user
        self.customer.updated_by = self.admin_user
        self.customer.save()

        # 2. Prepare an update as another authenticated user.
        self.customer.first_name = "Grace"
        request = SimpleNamespace(user=self.normal_user)
        manager = ActivityLogManager(self.customer, request)
        manager.set_changes()

        # 3. Confirm the immutable creator remains intact while the updater changes.
        self.assertEqual(self.customer.created_by, self.admin_user)
        self.assertEqual(self.customer.updated_by, self.normal_user)

    def test_serializer_lookup_registers_missing_serializer_lazily(self):
        _model_serializers.pop(self.CustomerModel, None)

        serializer_cls = get_serializer_cls(self.CustomerModel)

        self.assertIs(_model_serializers[self.CustomerModel], serializer_cls)

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
            "System changed the field 'department' to Finance",
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
            "System changed the fields 'first_name' and 'last_name'",
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
            "System changed the fields 'first_name', 'last_name' and more",
        )

    def test_condition_groups_reuse_typed_filter_lookup_evaluation(self) -> None:
        """AND groups and OR alternatives match typed values using shared lookups."""
        from bloomerp.filters.definition import Filter, FilterCondition

        settings = self.CustomerModel.bloomerp_config.activity_log_settings
        settings.conditions = [
            Filter(connector="OR", conditions=[
                FilterCondition(field_path="first_name", lookup_id="equals", value="Ada"),
                FilterCondition(field_path="first_name", lookup_id="equals", value="Grace"),
            ]),
            Filter(connector="AND", conditions=[
                FilterCondition(field_path="age", lookup_id="greater_than", value="20"),
            ]),
        ]
        self.assertTrue(ActivityLogManager(self.customer).matches_conditions())
        self.customer.age = 18
        self.assertFalse(ActivityLogManager(self.customer).matches_conditions())
        self.customer.age = 28
        self.customer.first_name = "Other"
        self.assertFalse(ActivityLogManager(self.customer).matches_conditions())

    def test_condition_false_suppresses_real_save_and_delete(self) -> None:
        """Signal paths honor a rejected model-value condition for changes and deletes."""
        from bloomerp.filters.definition import Filter, FilterCondition

        self.CustomerModel.bloomerp_config.activity_log_settings.conditions = [
            Filter(connector="AND", conditions=[
                FilterCondition(field_path="first_name", lookup_id="equals", value="Grace"),
            ])
        ]
        self.customer.age = 29
        self.customer.save()
        self.assertEqual(ActivityLog.objects.count(), 0)
        self.customer.delete()
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_invalid_conditions_preserve_audit_with_diagnostic(self) -> None:
        """A typo or unsupported relation never silently disables the audit trail."""
        from bloomerp.filters.definition import Filter, FilterCondition

        for path in ("missing_field", "country__name", "datetime_updated", "datetime_created"):
            with self.subTest(path=path):
                self.CustomerModel.bloomerp_config.activity_log_settings.conditions = [
                    Filter(connector="AND", conditions=[
                        FilterCondition(field_path=path, lookup_id="equals", value="anything"),
                    ])
                ]
                with self.assertLogs("bloomerp.services.activity_log_services", level="ERROR"):
                    self.assertTrue(ActivityLogManager(self.customer).matches_conditions())

    def test_default_and_ignored_change_paths_do_not_resolve_filter_metadata(self) -> None:
        """Absent conditions and ignored-only changes add no metadata or write queries."""
        manager = ActivityLogManager(self.customer)
        with self.assertNumQueries(0):
            self.assertTrue(manager.matches_conditions())
        self.CustomerModel.bloomerp_config.activity_log_settings.ignored_change_fields = frozenset({"age"})
        manager.payload = [{"field": "age", "from": 28, "to": 29}]
        with self.assertNumQueries(0):
            self.assertIsNone(manager.persist())

    def test_partial_save_uses_persisted_condition_value_and_actual_saved_fields(self) -> None:
        """Unwritten dirty fields neither change a condition nor create phantom diffs."""
        from bloomerp.filters.definition import Filter, FilterCondition

        self.CustomerModel.bloomerp_config.activity_log_settings.conditions = [
            Filter(connector="AND", conditions=[
                FilterCondition(field_path="first_name", lookup_id="equals", value="Ada"),
            ])
        ]
        self.customer.first_name = "Not saved"
        self.customer.age = 30
        self.customer.save(update_fields=["age"])
        log = ActivityLog.objects.get()
        self.assertEqual(log.payload, [{"field": "age", "from": 28, "to": 30}])

    def test_conditions_filter_creates_and_empty_group_semantics(self) -> None:
        """Empty OR rejects creation; empty AND and absent conditions retain it."""
        from bloomerp.filters.definition import Filter

        settings = self.CustomerModel.bloomerp_config.activity_log_settings
        settings.conditions = [Filter(connector="OR")]
        self.create_customer("Blocked", "Creation", 30)
        self.assertEqual(ActivityLog.objects.count(), 0)
        settings.conditions = [Filter(connector="AND")]
        self.create_customer("Allowed", "Creation", 30)
        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_current_user_condition_uses_activity_actor(self) -> None:
        """The shared current-user placeholder binds to this manager's request actor."""
        from bloomerp.filters.definition import Filter, FilterCondition

        self.customer.updated_by = self.admin_user
        self.customer.save(update_fields=["updated_by"])
        self.CustomerModel.bloomerp_config.activity_log_settings.conditions = [
            Filter(connector="AND", conditions=[
                FilterCondition(field_path="updated_by", lookup_id="equals_user", value="$user"),
            ])
        ]
        self.assertTrue(ActivityLogManager(self.customer, SimpleNamespace(user=self.admin_user)).matches_conditions())
        self.assertFalse(ActivityLogManager(self.customer, SimpleNamespace(user=self.normal_user)).matches_conditions())
        with self.assertLogs("bloomerp.services.activity_log_services", level="ERROR"):
            self.assertTrue(ActivityLogManager(self.customer).matches_conditions())

    def test_unknown_lookup_preserves_audit_with_diagnostic(self) -> None:
        """Invalid lookup configuration keeps the event instead of silently rejecting it."""
        from bloomerp.filters.definition import Filter, FilterCondition

        self.CustomerModel.bloomerp_config.activity_log_settings.conditions = [
            Filter(connector="AND", conditions=[
                FilterCondition(field_path="first_name", lookup_id="not_a_lookup", value="Ada"),
            ])
        ]
        manager = ActivityLogManager(self.customer)
        manager.payload = [{"field": "age", "from": 28, "to": 29}]
        with self.assertLogs("bloomerp.services.activity_log_services", level="ERROR"):
            manager.persist()
        self.assertEqual(ActivityLog.objects.count(), 1)

    def test_disabled_setting_precedes_condition_evaluation(self) -> None:
        """Disabled auditing does not query metadata or write even with conditions set."""
        from bloomerp.filters.definition import Filter

        settings = self.CustomerModel.bloomerp_config.activity_log_settings
        settings.enabled = False
        settings.conditions = [Filter(connector="AND")]
        manager = ActivityLogManager(self.customer)
        manager.payload = [{"field": "age", "from": 28, "to": 29}]
        with self.assertNumQueries(0):
            self.assertIsNone(manager.persist())

    def test_lookup_without_python_evaluation_keeps_audit(self) -> None:
        """SQL-only custom lookups fail open with a diagnostic instead of hiding events."""
        from unittest.mock import patch

        from bloomerp.filters.definition import Filter, FilterCondition
        from bloomerp.lookups.definition import BoundLookup

        self.CustomerModel.bloomerp_config.activity_log_settings.conditions = [
            Filter(connector="AND", conditions=[
                FilterCondition(field_path="first_name", lookup_id="equals", value="Ada"),
            ])
        ]
        with (
            patch.object(BoundLookup, "get_python_evaluator", return_value=None),
            self.assertLogs("bloomerp.services.activity_log_services", level="ERROR"),
        ):
            self.assertTrue(ActivityLogManager(self.customer).matches_conditions())
