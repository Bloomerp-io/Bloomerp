"""Check object search and exact selection label resolution."""

import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestSearchObjectsComponent(BloomerpComponentTestCase):
    """Tests function `search_objects` from `bloomerp/components/objects/search_objects.py`."""

    view_name = 'components_search_objects'

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise exact selection lookup with and without row access."""
        customer = self.CustomerModel.objects.first()
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        return [
            RequestScenario(
                name="selected ID resolves to its object label",
                user=self.admin_user,
                view_kwargs={"content_type_id": content_type.pk},
                query_params={"fk_selected_id": str(customer.pk)},
                expected=ExpectedResult(response_validators=self._has_selected_customer),
            ),
            RequestScenario(
                name="selected ID does not reveal an inaccessible row",
                user=self.normal_user,
                view_kwargs={"content_type_id": content_type.pk},
                query_params={"fk_selected_id": str(customer.pk)},
                expected=ExpectedResult(response_validators=self._has_no_objects),
            ),
        ]

    def _has_selected_customer(self, response: HttpResponse) -> bool:
        """Check that exact lookup returns the expected ID and display label."""
        customer = self.CustomerModel.objects.first()
        objects = json.loads(response.content)["objects"]
        return (
            len(objects) == 1
            and objects[0]["id"] == str(customer.pk)
            and objects[0]["string_representation"] == str(customer)
        )

    def _has_no_objects(self, response: HttpResponse) -> bool:
        """Check that a denied exact lookup reveals no object data."""
        return json.loads(response.content)["objects"] == []
