"""Exercise current-user filtering through the registered request middleware."""
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.middleware import current_request
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.tests.components.objects.dataviews.test_dataview_component import (
    filter_query_params,
)


class TestCurrentUserFilterComponent(BloomerpComponentTestCase):
    """Verify the reported Todo filter through synchronous and ASGI requests."""

    view_name = "components_dataview"
    auto_create_customers = False

    def extendedSetup(self) -> None:
        """Create two permitted users with separate assignments and an unassigned todo."""
        self.normal_user.is_superuser = True
        self.normal_user.save(update_fields=["is_superuser"])
        self.own_todo = Todo.objects.create(title="Current user's todo", assigned_to=self.admin_user)
        self.other_todo = Todo.objects.create(title="Other user's todo", assigned_to=self.normal_user)
        Todo.objects.create(title="Unassigned todo")
        self.kwargs = {"content_type_id": self.get_content_type_for_model(Todo).pk}
        self.filters = [Filter(connector="AND", conditions=[
            FilterCondition(field_path="assigned_to", lookup_id="equals_user", value="$user"),
        ])]
        self.params = filter_query_params(*self.filters)

    def contains_own_todo(self, response: HttpResponse) -> bool:
        """Require exactly the first requesting user's assigned todo."""
        return list(response.context["queryset"].values_list("pk", flat=True)) == [self.own_todo.pk]

    def contains_other_todo(self, response: HttpResponse) -> bool:
        """Require exactly the second requesting user's assigned todo."""
        return list(response.context["queryset"].values_list("pk", flat=True)) == [self.other_todo.pk]

    def preserves_current_user_preset(self, response: HttpResponse) -> bool:
        """Require the saved preset to retain its reusable current-user placeholder."""
        preset = SavedFilter.objects.get(pk=response.json()["id"])
        return preset.filters == [group.model_dump(mode="json") for group in self.filters]

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Run the same filter as two users through the real middleware stack."""
        return [
            RequestScenario(
                name="Saving a current-user preset retains the placeholder",
                view_name="components_filters_save",
                method="POST",
                user=self.admin_user,
                content_type="application/json",
                data={
                    "scope": "model",
                    "identifier": str(self.kwargs["content_type_id"]),
                    "name": "Assigned to current user",
                    "filters": [group.model_dump(mode="json") for group in self.filters],
                },
                expected=ExpectedResult(status_code=201, response_validators=self.preserves_current_user_preset),
            ),
            RequestScenario(
                name="Current-user filter selects the first user's assigned todo",
                user=self.admin_user,
                view_kwargs=self.kwargs,
                query_params=self.params,
                expected=ExpectedResult(response_validators=self.contains_own_todo),
            ),
            RequestScenario(
                name="The same filter resolves to the second requesting user",
                user=self.normal_user,
                view_kwargs=self.kwargs,
                query_params=self.params,
                expected=ExpectedResult(response_validators=self.contains_other_todo),
            ),
        ]

    async def test_current_user_filter_through_asgi(self) -> None:
        """Use case: ASGI dispatch; expected result: the middleware user reaches the sync view."""
        # 1. Authenticate an ASGI test client.
        await self.async_client.aforce_login(self.admin_user)

        # 2. Execute the reported filter through async middleware adaptation.
        response = await self.async_client.get(reverse(self.view_name, kwargs=self.kwargs), self.params)

        # 3. Only this user's todo is rendered and request context is cleaned up.
        self.assertEqual(response.status_code, 200)
        self.assertIn(str(self.own_todo.pk), response.content.decode())
        self.assertNotIn(str(self.other_todo.pk), response.content.decode())
        self.assertIsNone(current_request())
