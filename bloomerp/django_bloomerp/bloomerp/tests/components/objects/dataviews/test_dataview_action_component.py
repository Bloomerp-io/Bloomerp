"""Persist Todo completion dates through the routed Kanban move endpoint."""

from datetime import UTC, datetime

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.todo import Todo, TodoStatus
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)

COMPLETED_AT = datetime(2024, 1, 2, 3, 4, tzinfo=UTC)


class TestDataviewActionComponent(BloomerpComponentTestCase):
    """Exercise the same status-only persistence used by card dragging."""

    view_name = "components_dataview_renderer_operation"
    auto_create_customers = False

    def prepare_move(self, scenario: RequestScenario, *, completed: bool) -> None:
        """Create a real Todo and the user's Kanban preference for one request."""
        self.todo = Todo.objects.create(
            title="Kanban completion date",
            status=TodoStatus.COMPLETED if completed else TodoStatus.IN_PROGRESS,
            datetime_completed=COMPLETED_AT if completed else None,
        )
        content_type = ContentType.objects.get_for_model(Todo)
        preference = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference, {"content_type_id": content_type.pk}
        )
        config = KanbanDataView(display_fields=["title"], group_by_field="status")
        preference.view_type = config.view_type
        preference.options = {"kanban": config.dump_options()}
        title_field = ApplicationField.get_for_model(Todo).get(field="title")
        preference.set_visible_field_ids("kanban", [title_field.pk])
        preference.save(update_fields=["display_fields", "options", "view_type"])
        scenario.view_kwargs = {
            "content_type_id": content_type.pk,
            "preference_id": preference.pk,
            "action": "move",
        }
        scenario.data["object_id"] = str(self.todo.pk)

    def prepare_in_progress_todo(self, scenario: RequestScenario) -> None:
        """Prepare a card that has not yet been completed."""
        self.prepare_move(scenario, completed=False)

    def prepare_completed_todo(self, scenario: RequestScenario) -> None:
        """Prepare a card with a known original completion date."""
        self.prepare_move(scenario, completed=True)

    def has_completion_date(self, response: HttpResponse) -> bool:
        """Confirm the endpoint response and persisted completion agree."""
        self.todo.refresh_from_db()
        return (
            self.todo.status == TodoStatus.COMPLETED
            and self.todo.datetime_completed is not None
        )

    def preserves_completion_date(self, response: HttpResponse) -> bool:
        """Confirm repeated moves to Completed retain the first timestamp."""
        self.todo.refresh_from_db()
        return (
            self.todo.status == TodoStatus.COMPLETED
            and self.todo.datetime_completed == COMPLETED_AT
        )

    def clears_completion_date(self, response: HttpResponse) -> bool:
        """Confirm a move out of Completed removes the persisted timestamp."""
        self.todo.refresh_from_db()
        return (
            self.todo.status == TodoStatus.IN_PROGRESS
            and self.todo.datetime_completed is None
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover completion, reopening and repeated completion through HTTP."""
        return [
            RequestScenario(
                name="Kanban completes a todo",
                method="POST",
                user=self.admin_user,
                prepare=self.prepare_in_progress_todo,
                data={"group_value": TodoStatus.COMPLETED},
                expected=ExpectedResult(
                    status_code=200, response_validators=self.has_completion_date
                ),
            ),
            RequestScenario(
                name="Kanban reopens a todo",
                method="POST",
                user=self.admin_user,
                prepare=self.prepare_completed_todo,
                data={"group_value": TodoStatus.IN_PROGRESS},
                expected=ExpectedResult(
                    status_code=200, response_validators=self.clears_completion_date
                ),
            ),
            RequestScenario(
                name="Kanban repeats completion",
                method="POST",
                user=self.admin_user,
                prepare=self.prepare_completed_todo,
                data={"group_value": TodoStatus.COMPLETED},
                expected=ExpectedResult(
                    status_code=200, response_validators=self.preserves_completion_date
                ),
            ),
        ]
