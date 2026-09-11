from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    ModelRequestScenario,
    RequestScenario,
)


class TestObjectTodosView(BloomerpDetailViewTestCase):
    view_name = "todos"
    model = None

    def get_test_scenarios(self) -> list[RequestScenario]:
        customer = self.CustomerModel.objects.create(
            first_name="John", last_name="Doe", age=20
        )

        return [
            ModelRequestScenario(
                name="Admin user can view Todo's of model",
                method="GET",
                user=self.admin_user,
                model=self.CustomerModel,
                expected=ExpectedResult(
                    status_code=200,
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
