from bloomerp.models.forms.form import Form
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpDetailViewTestCase,
    ExpectedResult,
    RequestScenario,
    ModelRequestScenario,
)


class TestBuilderView(BloomerpDetailViewTestCase):
    view_name = 'form_builder'
    model = Form

    def create_test_object(self):
        return Form.objects.create(
            name="Default form",
            content_type=self.get_content_type_for_model(Todo)
        )
    
    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="Accessible to admin user",
                method="GET",
                user=self.admin_user,
                expected=ExpectedResult(
                    200,
                    response_validators=[
                        self.contains_text("Search"),
                        self.contains_text("Initial Data"),
                        self.contains_text("Edit"),
                        self.contains_text("Add items"),
                    ]
                )
            ),
            RequestScenario(
                name="Inaccessible to normal user",
                user=self.normal_user,
                expected=ExpectedResult(
                    403
                )
            )
        ]
