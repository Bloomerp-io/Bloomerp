from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpComponentTestCase, ExpectedResult, RequestScenario


class TestActivityLogComponent(BloomerpComponentTestCase):
    """Tests rendering an object's activity history."""

    view_name = "components_activity_log"

    def get_test_scenarios(self) -> list[RequestScenario]:
        content_type = self.get_content_type_for_model(Todo)
        title_1 = "A very cool todo"
        title_2 = "Some other cool todo"

        obj = Todo.objects.create(title=title_1)
        obj.title = title_2

        obj.save()
        query_params = {
            "content_type_id": content_type.id,
            "object_id": obj.id,
        }

        return [
            RequestScenario(
                name="authorized user",
                method="GET",
                user=self.admin_user,
                query_params=query_params,
                expected=ExpectedResult(
                    status_code=200,
                    response_validators=[
                        self.contains_text(title_1),
                        self.contains_text(title_2),
                    ]
                ),
            ),
            RequestScenario(
                name="unauthorized user",
                method="GET",
                user=self.normal_user,
                query_params=query_params,
                expected=ExpectedResult(status_code=403),
            ),
        ]
