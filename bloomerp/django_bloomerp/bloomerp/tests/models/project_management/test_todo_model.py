"""Database-backed completion-date contracts for Todo saves."""

from datetime import UTC, datetime

from bloomerp.models.project_management.todo import Todo, TodoStatus
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario

COMPLETED_AT = datetime(2024, 1, 2, 3, 4, tzinfo=UTC)


class TestTodoModel(BloomerpModelTestCase):
    model = Todo

    def complete_with_partial_save(self, todo: Todo) -> None:
        """Persist only status, just as a Kanban move does."""
        original_title = todo.title
        todo.title = "Unsaved title"
        todo.status = TodoStatus.COMPLETED
        fields = ["status"]
        todo.save(update_fields=fields)
        todo.refresh_from_db()
        self.assertEqual(todo.title, original_title)
        self.assertEqual(fields, ["status"])

    def reopen_with_partial_save(self, todo: Todo) -> None:
        """Reopen a completed todo using an immutable field collection."""
        todo.status = TodoStatus.IN_PROGRESS
        todo.save(update_fields=frozenset({"status"}))
        todo.refresh_from_db()

    def save_title_with_unsaved_completion(self, todo: Todo) -> None:
        """Do not persist completion changes when only the title is saved."""
        todo.status = TodoStatus.COMPLETED
        todo.title = "Renamed"
        todo.save(update_fields=["title"])
        todo.refresh_from_db()
        self.assertEqual(todo.title, "Renamed")

    def save_title_with_unsaved_reopen(self, todo: Todo) -> None:
        """Do not clear a persisted date when the reopened status is unsaved."""
        todo.status = TodoStatus.IN_PROGRESS
        todo.title = "Renamed"
        todo.save(update_fields=["title"])
        todo.refresh_from_db()
        self.assertEqual(todo.title, "Renamed")

    def save_nothing(self, todo: Todo) -> None:
        """Keep an empty update_fields collection a database no-op."""
        todo.status = TodoStatus.COMPLETED
        todo.save(update_fields=[])
        todo.refresh_from_db()

    def is_completed_with_date(self, todo: Todo) -> bool:
        """Require the completed status and date to survive database refresh."""
        return (
            todo.status == TodoStatus.COMPLETED and todo.datetime_completed is not None
        )

    def is_original_completion(self, todo: Todo) -> bool:
        """Require repeated completion to preserve its original timestamp."""
        return (
            todo.status == TodoStatus.COMPLETED
            and todo.datetime_completed == COMPLETED_AT
        )

    def is_reopened(self, todo: Todo) -> bool:
        """Require a reopened todo to have no completion date."""
        return todo.status == TodoStatus.IN_PROGRESS and todo.datetime_completed is None

    def is_backlog_without_date(self, todo: Todo) -> bool:
        """Require an unsaved status change to leave persisted state untouched."""
        return todo.status == TodoStatus.BACKLOG and todo.datetime_completed is None

    def get_test_scenarios(self) -> list[ModelScenario[Todo]]:
        """Exercise full saves and partial status updates against the database."""
        return [
            ModelScenario(
                name="Full save completes a todo",
                create_args={"title": "Full save"},
                update_args={"status": TodoStatus.COMPLETED},
                update_validators=self.is_completed_with_date,
            ),
            ModelScenario(
                name="Partial status save persists completion date",
                create_args={"title": "Complete"},
                post_create=self.complete_with_partial_save,
                create_validators=self.is_completed_with_date,
            ),
            ModelScenario(
                name="Partial status save clears completion date on reopening",
                create_args={
                    "title": "Reopen",
                    "status": TodoStatus.COMPLETED,
                    "datetime_completed": COMPLETED_AT,
                },
                post_create=self.reopen_with_partial_save,
                create_validators=self.is_reopened,
            ),
            ModelScenario(
                name="Repeated partial completion preserves the original date",
                create_args={
                    "title": "Repeat",
                    "status": TodoStatus.COMPLETED,
                    "datetime_completed": COMPLETED_AT,
                },
                post_create=self.complete_with_partial_save,
                create_validators=self.is_original_completion,
            ),
            ModelScenario(
                name="Unrelated partial save does not persist unsaved completion",
                create_args={"title": "Unrelated"},
                post_create=self.save_title_with_unsaved_completion,
                create_validators=self.is_backlog_without_date,
            ),
            ModelScenario(
                name="Unrelated partial save does not clear persisted completion",
                create_args={
                    "title": "Unrelated",
                    "status": TodoStatus.COMPLETED,
                    "datetime_completed": COMPLETED_AT,
                },
                post_create=self.save_title_with_unsaved_reopen,
                create_validators=self.is_original_completion,
            ),
            ModelScenario(
                name="Empty update fields does not persist completion",
                create_args={"title": "No-op"},
                post_create=self.save_nothing,
                create_validators=self.is_backlog_without_date,
            ),
        ]
