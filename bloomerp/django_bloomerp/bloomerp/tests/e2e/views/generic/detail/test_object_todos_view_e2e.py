from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpE2ETestCase,
    E2EAction,
    E2ERequestScenario,
)
from bloomerp.utils.models import get_detail_base_view_url


class TestObjectTodosViewE2E(BloomerpE2ETestCase):
    """Tests class `ObjectTodosView` from `bloomerp/views/generic/detail/todos.py`."""

    view_name = "todos"

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Verify the related to-do dataview loads in the browser."""
        customer = self.CustomerModel.objects.create(
            first_name="Related", last_name="Customer", age=20
        )
        Todo.objects.create(
            title="Attached to-do",
            content_type=ContentType.objects.get_for_model(customer),
            object_id=str(customer.pk),
        )
        url = reverse(
            get_detail_base_view_url(self.CustomerModel) + "_todos",
            kwargs={"pk": customer.pk},
        )
        dataview_selector = f"#data-view-{ContentType.objects.get_for_model(Todo).pk}"

        return [
            E2ERequestScenario(
                name="Admin sees attached to-dos after the dataview loads",
                user=self.admin_user,
                url=url,
                actions=[
                    E2EAction(
                        name="Wait for the to-do dataview",
                        execute=self.expect_visible(dataview_selector),
                        validators=[
                            self.expect_text("Attached to-do"),
                        ],
                    )
                ],
            )
        ]
