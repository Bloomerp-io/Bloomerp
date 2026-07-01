from bloomerp.models.project_management import Initiative, InitiativeStatus, Todo
from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestInitiative(BaseBloomerpModelTestCase):
    auto_create_customers = False

    def test_initiative_todo_count(self):
        """
        Use case: A project-management initiative has multiple to-dos assigned.
        Expected result: The initiative exposes the number of assigned to-dos.
        """
        # 1. Create an initiative.
        initiative = Initiative.objects.create(name="Launch customer portal")

        # 2. Create two to-dos assigned to the initiative and one unrelated to-do.
        Todo.objects.create(title="Design flow", initiative=initiative)
        Todo.objects.create(title="Build flow", initiative=initiative)
        Todo.objects.create(title="Unrelated work")

        # 3. Check that only assigned to-dos are counted.
        self.assertEqual(initiative.todo_count, 2)

    def test_initiative_auto_fills_completed_at_if_completed(self):
        """
        Use case: An initiative is saved with the completed status.
        Expected result: The completed timestamp is automatically set.
        """
        # 1. Create a completed initiative without a completed timestamp.
        initiative = Initiative.objects.create(
            name="Launch customer portal",
            status=InitiativeStatus.COMPLETED,
        )

        # 2. Check that the model filled the completed timestamp.
        self.assertIsNotNone(initiative.completed_at)

    def test_initiative_clears_completed_at_if_status_changed(self):
        """
        Use case: A completed initiative is moved back to another status.
        Expected result: The completed timestamp is cleared.
        """
        # 1. Create a completed initiative.
        initiative = Initiative.objects.create(
            name="Launch customer portal",
            status=InitiativeStatus.COMPLETED,
        )
        self.assertIsNotNone(initiative.completed_at)

        # 2. Change the initiative away from completed.
        initiative.status = InitiativeStatus.IN_PROGRESS
        initiative.save()

        # 3. Check that the completed timestamp was cleared.
        self.assertIsNone(initiative.completed_at)
