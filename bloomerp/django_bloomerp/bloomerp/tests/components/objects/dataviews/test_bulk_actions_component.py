from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType

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
