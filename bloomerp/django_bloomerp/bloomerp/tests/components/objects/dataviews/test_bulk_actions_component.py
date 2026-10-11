from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

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
