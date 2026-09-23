from bloomerp.models.project_management.todo import Todo
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    ModelRequestScenario,
    RequestScenario,
)


class TestObjectTodosView(BloomerpDetailViewTestCase):
    view_name = "todos"
    model = None

    def has_related_todo_filters(self, response: HttpResponse) -> bool:
        """Check that the dataview uses valid filters for this customer."""
        return response.context["filters"] == {
            "object_id": str(self.customer.pk),
            "content_type": ContentType.objects.get_for_model(self.CustomerModel).pk,
        }

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise the object to-do page and its access rules."""
        customer = self.CustomerModel.objects.create(
            first_name="John", last_name="Doe", age=20
        )
        self.customer = customer

        return [
            ModelRequestScenario(
                name="Admin user can view Todo's of model",
                method="GET",
                user=self.admin_user,
                model=self.CustomerModel,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[self.has_related_todo_filters],
                ),
                view_kwargs={"pk": customer.id},
            ),
            ModelRequestScenario(
                name="Normal user can't",
                method="GET",
                user=self.normal_user,
                model=self.CustomerModel,
                expected=ExpectedResult(
                    status_code=403,
                ),
                view_kwargs={"pk": customer.id},
            ),
        ]

    def test_todo_model_does_not_have_a_todos_route(self):
        with self.assertRaisesRegex(AssertionError, "found 0"):
            self.get_route(model=Todo)
