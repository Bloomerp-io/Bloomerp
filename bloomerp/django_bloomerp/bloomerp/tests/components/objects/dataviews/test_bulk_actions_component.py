import json
from typing import Any
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import PolicyManager
from bloomerp.services.bulk_action_services import execute_bulk_delete
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestBulkActionsComponent(BloomerpComponentTestCase):
    """Tests rendering and executing bulk object actions."""

    auto_create_customers = False
    view_name = "components_bulk_actions"

    def get_test_scenarios(self) -> list[RequestScenario]:
        selected = self.create_customer("Selected", "Customer", 30)
        unselected = self.create_customer("Unselected", "Customer", 31)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        view_kwargs = {"content_type_id": content_type.pk}
        query_params = {
            "selection": "selected",
            "object_ids": str(selected.pk),
        }
        return [
            RequestScenario(
                name="render permitted bulk delete action",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                query_params=query_params,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Delete 1 object(s)"),
                        self.contains_text('name="action" value="bulk_delete"'),
                    ],
                ),
            ),
            RequestScenario(
                name="delete selected objects",
                method="POST",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                query_params=query_params,
                data={"action": "bulk_delete"},
                headers={"HX-Request": "true"},
                prepare=self._disable_celery,
                expected=ExpectedResult(
                    response_validators=[
                        self._object_does_not_exist(selected.pk),
                        self._object_exists(unselected.pk),
                        self._header_contains(
                            "HX-Trigger-After-Swap",
                            "bloomerp:bulk-action-complete",
                        ),
                    ],
                ),
            ),
            RequestScenario(
                name="reject missing bulk action",
                method="POST",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                query_params=query_params,
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=self._object_exists(selected.pk),
                ),
            ),
            RequestScenario(
                name="reject non-bulk permission action",
                method="POST",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                query_params=query_params,
                data={"action": "view"},
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=self._object_exists(selected.pk),
                ),
            ),
        ]

    def _disable_celery(self, _setup: RequestScenario) -> None:
        celery_patch = patch(
            "bloomerp.utils.async_utils.is_celery_available",
            return_value=False,
        )
        celery_patch.start()
        self.addCleanup(celery_patch.stop)

    def _object_exists(self, object_id):
        return self._named_validator(
            f"object_exists({object_id!r})",
            lambda _response: self.CustomerModel.objects.filter(pk=object_id).exists(),
        )

    def _object_does_not_exist(self, object_id):
        return self._named_validator(
            f"object_does_not_exist({object_id!r})",
            lambda _response: not self.CustomerModel.objects.filter(
                pk=object_id
            ).exists(),
        )

    def _header_contains(self, name: str, value: str):
        return self._named_validator(
            f"header_contains({name!r}, {value!r})",
            lambda response: value in response.headers.get(name, ""),
        )


class TestBulkAddressUpdates(BloomerpComponentTestCase):
    """Exercise multipart address submissions through the real bulk endpoint."""

    auto_create_customers = False
    view_name = "components_bulk_actions"

    @classmethod
    def setUpClass(cls) -> None:
        """Create an isolated address-bearing model for component scenarios."""
        from django.db import models

        from bloomerp.model_fields.address_field import AddressField
        from bloomerp.tests.utils.dynamic_models import create_test_models

        super().setUpClass()
        cls.AddressModel = create_test_models(
            app_label="bloomerp",
            model_defs={"BulkAddressComponentRecord": {
                "name": models.CharField(max_length=100),
                "address": AddressField(blank=True, null=True),
                "value_amount": models.IntegerField(default=0),
                "value_0": models.IntegerField(default=0),
            }},
            use_bloomerp_base=True,
        )["BulkAddressComponentRecord"]
        cls._register_dynamic_model_routes([cls.AddressModel])

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover extraction, clearing, validation, and permission boundaries."""
        from bloomerp.models import ApplicationField

        self.original = {"street_1": "Old street", "country": "BE"}
        self.selected = self.AddressModel.objects.create(name="Selected", address=self.original, value_amount=1, value_0=1)
        self.unselected = self.AddressModel.objects.create(name="Unselected", address=self.original)
        field = ApplicationField.get_by_field(self.AddressModel, "address")
        common = {
            "method": "POST",
            "user": self.admin_user,
            "view_kwargs": {"content_type_id": ContentType.objects.get_for_model(self.AddressModel).pk},
            "query_params": {"selection": "selected", "object_ids": str(self.selected.pk)},
            "headers": {"HX-Request": "true"},
            "prepare": self._disable_celery,
        }
        data = {"action": "bulk_change", "application_field_id": str(field.pk)}
        return [
            RequestScenario(
                name="persist all six address components on selected rows",
                **common,
                data={**data, **dict(zip(
                    [f"value_{index}" for index in range(6)],
                    ["New street", "Unit 2", "94105", "San Francisco", "California", "US"],
                ))},
                expected=ExpectedResult(response_validators=self._address_updated),
            ),
            RequestScenario(
                name="retain legitimate value-prefixed filters during bulk updates",
                **{**common, "query_params": {"value_amount__gte": "1"}},
                data={**data, **dict(zip(
                    [f"value_{index}" for index in range(6)],
                    ["New street", "Unit 2", "94105", "San Francisco", "California", "US"],
                ))},
                expected=ExpectedResult(response_validators=self._address_updated),
            ),
            RequestScenario(
                name="render only rows matching a numeric value field filter",
                **{**common, "method": "GET", "query_params": {"value_0": "1"}},
                expected=ExpectedResult(response_validators=[
                    self.contains_text("Delete 1 object(s)"),
                    self.does_not_contain_text("Delete 2 object(s)"),
                    self.contains_text('hx-include="this"'),
                ]),
            ),
            RequestScenario(
                name="retain numeric value field filters during bulk updates",
                **{**common, "query_params": {"value_0": "1"}},
                data={**data, **dict(zip(
                    [f"value_{index}" for index in range(6)],
                    ["New street", "Unit 2", "94105", "San Francisco", "California", "US"],
                ))},
                expected=ExpectedResult(response_validators=self._address_updated),
            ),
            RequestScenario(
                name="retain numeric value field filters during bulk deletion",
                **{**common, "query_params": {"value_0": "1"}},
                data={"action": "bulk_delete"},
                expected=ExpectedResult(response_validators=self._filtered_record_deleted),
            ),
            RequestScenario(
                name="intersect selected ids with numeric field filters",
                **{**common, "query_params": {
                    "value_0": "1", "selection": "selected",
                    "object_ids": str(self.unselected.pk),
                }},
                data={"action": "bulk_delete"},
                expected=ExpectedResult(status_code=400, response_validators=self._both_records_preserved),
            ),
            RequestScenario(
                name="clear optional address with empty components",
                **common,
                data={**data, **{f"value_{index}": "" for index in range(6)}},
                expected=ExpectedResult(response_validators=self._address_cleared),
            ),
            RequestScenario(
                name="accept a partial address with only region and country",
                **common,
                data={**data, "value_4": "Brussels", "value_5": "BE"},
                expected=ExpectedResult(response_validators=self._partial_address_updated),
            ),
            RequestScenario(
                name="reject invalid country without changing records or closing modal",
                **common,
                data={**data, "value_0": "New street", "value_5": "INVALID"},
                expected=ExpectedResult(response_validators=[
                    self._address_unchanged,
                    self.contains_text("Select a valid choice"),
                    self.contains_text('value="New street"'),
                    self.header_equals("HX-Retarget", "#bulk-action-field-value"),
                ]),
            ),
            RequestScenario(
                name="queue multipart values without losing address components",
                **{**common, "prepare": self._queue_update},
                data={**data, "value_0": "Queued street", "value_4": "Brussels", "value_5": "BE"},
                expected=ExpectedResult(response_validators=self._queued_address),
            ),
            RequestScenario(
                name="deny an address update without bulk permission",
                **{**common, "user": self.normal_user},
                data={**data, "value_0": "Forbidden"},
                expected=ExpectedResult(status_code=403, response_validators=self._address_unchanged),
            ),
        ]

    def _disable_celery(self, _scenario: RequestScenario) -> None:
        """Run the real service synchronously without an external worker."""
        celery_patch = patch("bloomerp.utils.async_utils.is_celery_available", return_value=False)
        celery_patch.start()
        self.addCleanup(celery_patch.stop)

    def _address_updated(self, response: "HttpResponse") -> bool:
        """Verify all components persist and unselected rows remain unchanged."""
        self.selected.refresh_from_db()
        self.unselected.refresh_from_db()
        return self.selected.address == {
            "street_1": "New street", "street_2": "Unit 2", "postal_code": "94105",
            "city": "San Francisco", "state": "California", "country": "US",
        } and self.unselected.address["street_1"] == "Old street" and "bloomerp:bulk-action-complete" in response.headers.get("HX-Trigger-After-Swap", "")

    def _address_cleared(self, _response: "HttpResponse") -> bool:
        """Verify empty multipart inputs intentionally clear an optional address."""
        self.selected.refresh_from_db()
        return self.selected.address is None

    def _partial_address_updated(self, _response: "HttpResponse") -> bool:
        """Verify omitted optional components are empty, not stale."""
        self.selected.refresh_from_db()
        return self.selected.address == {
            "street_1": "", "street_2": "", "postal_code": "", "city": "",
            "state": "Brussels", "country": "BE",
        }

    def _address_unchanged(self, response: "HttpResponse") -> bool:
        """Verify rejected submissions neither mutate the address nor close the modal."""
        self.selected.refresh_from_db()
        return self.selected.address["street_1"] == "Old street" and "HX-Trigger-After-Swap" not in response.headers

    def _queue_update(self, _scenario: RequestScenario) -> None:
        """Observe the serializable dispatch boundary without an external worker."""
        queue_patch = patch(
            "bloomerp.components.objects.dataviews.bulk_actions.run_async_or_sync",
            return_value=(True, None),
        )
        self.queue_mock = queue_patch.start()
        self.addCleanup(queue_patch.stop)

    def _queued_address(self, response: HttpResponse) -> bool:
        """Verify queuing preserves subfield order while leaving local rows unchanged."""
        from bloomerp.utils.async_utils import deserialize_value, serialize_value

        self.selected.refresh_from_db()
        value = self.queue_mock.call_args.kwargs["value"]
        return (
            value == ["Queued street", None, None, None, "Brussels", "BE"]
            and deserialize_value(serialize_value(value)) == value
            and self.selected.address["street_1"] == "Old street"
            and "queued" in response.content.decode()
        )

    def _filtered_record_deleted(self, _response: HttpResponse) -> bool:
        """Ensure all-filtered deletion affects only the matching numeric-field row."""
        return (
            not self.AddressModel.objects.filter(pk=self.selected.pk).exists()
            and self.AddressModel.objects.filter(pk=self.unselected.pk).exists()
        )

    def _both_records_preserved(self, _response: HttpResponse) -> bool:
        """Ensure an empty intersection never deletes either selected or matching rows."""
        return self.AddressModel.objects.filter(
            pk__in=[self.selected.pk, self.unselected.pk],
        ).count() == 2


class TestBulkFilterRecovery(BloomerpComponentTestCase):
    """Keep recovered list filters and bulk targets aligned at the HTTP boundary."""

    auto_create_customers = False
    view_name = "components_bulk_actions"

    def setUp(self) -> None:
        """Grant view and bulk-delete access to three rows, hiding one field."""
        super().setUp()
        self.nonmatching = self.create_customer("Below filter", "Private", 10)
        self.matching = self.create_customer("Selected match", "Private", 20)
        self.unselected = self.create_customer("Unselected match", "Private", 30)
        self.restricted = self.create_customer("Restricted match", "Private", 40)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.policy = PolicyManager.create_policy(
            self.CustomerModel,
            access_rule=AccessRule(
                row_permissions=[RowPolicyRuleContent(
                    connector="AND",
                    conditions=[FilterCondition(
                        field_path="age", lookup_id="less_than_or_equal", value=30,
                    )],
                    permissions=[BloomerpPermission.VIEW],
                )],
                field_permissions={
                    "first_name": [BloomerpPermission.VIEW],
                    "age": [BloomerpPermission.VIEW],
                },
            ),
            global_permissions=[BloomerpPermission.VIEW, BloomerpPermission.BULK_DELETE],
        )
        # Match stored bulk row grants used by the service tests. The policy
        # factory exposes bulk-delete only globally, while stored row rules
        # still participate in the endpoint and worker's authorized queryset.
        self.policy.row_policy.rules.get().add_permission("bulk_delete_customer")
        self.policy.assign_user(self.normal_user)

    def _recovery_query(self, selected: bool = False) -> dict[str, Any]:
        """Combine a valid JSON sibling, malformed inputs, and a forbidden field."""
        valid_group = Filter(connector="AND", conditions=[FilterCondition(
            field_path="age", lookup_id="greater_than_or_equal", value=20,
        )]).model_dump()
        query: dict[str, Any] = {
            "selection": "filtered",
            "filter": [
                json.dumps([valid_group, {"connector": "AND", "conditions": "invalid sibling"}]),
                "{malformed JSON",
            ],
            "last_name": "Forbidden filter value",
        }
        if selected:
            query.update({
                "selection": "selected",
                "object_ids": [
                    str(self.matching.pk), str(self.nonmatching.pk), str(self.restricted.pk),
                ],
            })
        return query

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise single-request recovery, defaults, and selection isolation."""
        common = {
            "user": self.normal_user,
            "view_kwargs": {"content_type_id": self.content_type.pk},
        }
        return [
            RequestScenario(
                name="preview only effective filters after malformed and forbidden inputs",
                **common,
                query_params=self._recovery_query(),
                expected=ExpectedResult(response_validators=[
                    self._all_filtered_preview, self._effective_summary,
                ]),
            ),
            RequestScenario(
                name="intersect selected ids with recovered filters and authorized rows",
                **common,
                query_params=self._recovery_query(selected=True),
                expected=ExpectedResult(response_validators=[
                    self._selected_preview, self._effective_summary,
                ]),
            ),
            RequestScenario(
                name="preserve default filters while recovering user filters",
                **common,
                query_params=self._recovery_query(),
                prepare=self._add_default_filter,
                expected=ExpectedResult(response_validators=[
                    self._selected_preview, self._effective_summary,
                ]),
            ),
            RequestScenario(
                name="all-filtered post deletes only recovered authorized matches",
                **common,
                method="POST",
                query_params=self._recovery_query(),
                data={"action": "bulk_delete"},
                prepare=self._disable_celery,
                cleanup=self._restore_celery,
                expected=ExpectedResult(response_validators=self._all_filtered_deleted),
            ),
            RequestScenario(
                name="selected post preserves nonmatching restricted and unselected rows",
                **common,
                method="POST",
                query_params=self._recovery_query(selected=True),
                data={"action": "bulk_delete"},
                prepare=self._disable_celery,
                cleanup=self._restore_celery,
                expected=ExpectedResult(response_validators=self._selected_deleted),
            ),
            RequestScenario(
                name="default filters also narrow the recovered bulk post",
                **common,
                method="POST",
                query_params=self._recovery_query(),
                data={"action": "bulk_delete"},
                prepare=[self._add_default_filter, self._disable_celery],
                cleanup=self._restore_celery,
                expected=ExpectedResult(response_validators=self._selected_deleted),
            ),
            RequestScenario(
                name="empty explicit selection never broadens to all recovered matches",
                **common,
                method="POST",
                query_params={**self._recovery_query(), "selection": "selected"},
                data={"action": "bulk_delete"},
                expected=ExpectedResult(status_code=400, response_validators=self._all_preserved),
            ),
        ]

    def _add_default_filter(self, _scenario: RequestScenario) -> None:
        """Limit the default preference to one of the recovered matches."""
        preference = PreferenceManager(self.normal_user).get_or_create_selected(
            UserListViewPreference, scope={"content_type_id": self.content_type.pk},
        )
        saved_filter = SavedFilter.objects.create(
            name="Bulk recovery default", scope="model", identifier=str(self.content_type.pk),
            filters=[Filter(connector="AND", conditions=[FilterCondition(
                field_path="age", lookup_id="equals", value=20,
            )]).model_dump()],
        )
        preference.add_default_filter(saved_filter)

    def _disable_celery(self, _scenario: RequestScenario) -> None:
        """Execute the actual bulk worker inline for one isolated scenario."""
        self.celery_patch = patch("bloomerp.utils.async_utils.is_celery_available", return_value=False)
        self.celery_patch.start()

    def _restore_celery(self, _scenario: RequestScenario) -> None:
        """Restore asynchronous dispatch immediately after the scenario."""
        self.celery_patch.stop()

    def _effective_summary(self, response: HttpResponse) -> bool:
        """Show the retained age filter without claiming rejected inputs apply."""
        summary = json.dumps(response.context["query_summary"])
        return (
            "age" in summary
            and "last_name" not in summary
            and "Forbidden filter value" not in summary
            and "invalid sibling" not in summary
            and "malformed JSON" not in summary
        )

    def _all_filtered_preview(self, response: HttpResponse) -> bool:
        """Confirm malformed filters never widen the preview beyond two matches."""
        return response.context["count"] == 2 and response.context["delete_count"] == 2

    def _selected_preview(self, response: HttpResponse) -> bool:
        """Confirm selected ids or defaults further narrow the authorized matches."""
        return response.context["count"] == 1 and response.context["delete_count"] == 1

    def _all_filtered_deleted(self, response: HttpResponse) -> bool:
        """Verify all-filtered POST leaves both nonmatches and unauthorized rows."""
        return (
            set(self.CustomerModel.objects.values_list("pk", flat=True))
            == {self.nonmatching.pk, self.restricted.pk}
            and "bloomerp:bulk-action-complete" in response.headers.get("HX-Trigger-After-Swap", "")
        )

    def _selected_deleted(self, response: HttpResponse) -> bool:
        """Verify explicit selection deletes only its one authorized filter match."""
        return (
            set(self.CustomerModel.objects.values_list("pk", flat=True))
            == {self.nonmatching.pk, self.unselected.pk, self.restricted.pk}
            and "bloomerp:bulk-action-complete" in response.headers.get("HX-Trigger-After-Swap", "")
        )

    def _all_preserved(self, _response: HttpResponse) -> bool:
        """Confirm an empty or rejected action preserves every fixture."""
        return self.CustomerModel.objects.count() == 4

    def test_list_preview_and_post_share_recovered_targets(self) -> None:
        """Follow both server-side journeys; one request scenario cannot retain responses.

        This specialized integration method follows the testing guide's exception
        for multi-step behavior. It checks endpoint state without browser wiring.
        """
        self.client.force_login(self.normal_user)
        kwargs = {"content_type_id": self.content_type.pk}
        list_url = reverse("components_dataview", kwargs=kwargs)
        bulk_url = reverse(self.view_name, kwargs=kwargs)
        for selected in (False, True):
            with self.subTest(selected=selected), transaction.atomic():
                try:
                    list_query = self._recovery_query()
                    list_query.pop("selection")
                    listing = self.client.get(list_url, query_params=list_query)
                    self.assertEqual(listing.status_code, 200)
                    visible_ids = {entry.pk for entry in listing.context["queryset"]}
                    self.assertSetEqual(visible_ids, {self.matching.pk, self.unselected.pk})
                    self.assertEqual(
                        [condition.field_path for group in listing.context["filters"] for condition in group.conditions],
                        ["age"],
                    )
                    query = self._recovery_query(selected=selected)
                    expected_ids = visible_ids & {self.matching.pk} if selected else visible_ids
                    preview = self.client.get(bulk_url, query_params=query)
                    self.assertEqual(preview.status_code, 200)
                    self.assertEqual(preview.context["delete_count"], len(expected_ids))
                    self.assertTrue(self._effective_summary(preview))
                    with patch("bloomerp.utils.async_utils.is_celery_available", return_value=False):
                        result = self.client.post(
                            preview.context["submit_url"], data={"action": "bulk_delete"},
                        )
                    self.assertEqual(result.status_code, 200)
                    remaining_ids = set(self.CustomerModel.objects.values_list("pk", flat=True))
                    self.assertSetEqual(
                        remaining_ids,
                        {self.nonmatching.pk, self.matching.pk, self.unselected.pk, self.restricted.pk} - expected_ids,
                    )
                finally:
                    transaction.set_rollback(True)

    def _queue_recovered_delete(self) -> dict[str, Any]:
        """Capture the real endpoint's serialized worker arguments after recovery."""
        self.client.force_login(self.normal_user)
        with patch(
            "bloomerp.components.objects.dataviews.bulk_actions.run_async_or_sync",
            return_value=(True, None),
        ) as dispatch:
            response = self.client.post(
                reverse(self.view_name, kwargs={"content_type_id": self.content_type.pk}),
                query_params=self._recovery_query(), data={"action": "bulk_delete"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "queued")
        self.assertIs(dispatch.call_args.args[0], execute_bulk_delete)
        worker_args = dispatch.call_args.kwargs
        self.assertSetEqual(set(worker_args["object_ids"]), {str(self.matching.pk), str(self.unselected.pk)})
        self.assertEqual(self.CustomerModel.objects.count(), 4)
        return worker_args

    def test_worker_rechecks_bulk_permission_after_recovery(self) -> None:
        """Reject a queued action when its user's global bulk permission is revoked."""
        worker_args = self._queue_recovered_delete()
        bulk_permission = self.policy.global_permissions.get(codename="bulk_delete_customer")
        self.policy.global_permissions.remove(bulk_permission)
        with self.assertRaises(PermissionDenied):
            execute_bulk_delete(**worker_args)
        self.assertEqual(self.CustomerModel.objects.count(), 4)

    def test_worker_rechecks_authorized_rows_after_recovery(self) -> None:
        """Narrow queued identifiers again if row permissions change before execution."""
        worker_args = self._queue_recovered_delete()
        row_rule = self.policy.row_policy.rules.get()
        row_rule.rule = Filter(connector="AND", conditions=[FilterCondition(
            field_path="age", lookup_id="equals", value=20,
        )]).model_dump()
        row_rule.save()
        self.assertEqual(execute_bulk_delete(**worker_args), 1)
        self.assertSetEqual(
            set(self.CustomerModel.objects.values_list("pk", flat=True)),
            {self.nonmatching.pk, self.unselected.pk, self.restricted.pk},
        )
