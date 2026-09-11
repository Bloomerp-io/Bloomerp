from playwright.sync_api import expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import e2e_test_case as e2e


class TestItemNavigationE2E(e2e.BloomerpE2ETestCase):
    def get_test_scenarios(self):
        todo = Todo.objects.create(title="Keyboard navigation")
        return [e2e.E2ERequestScenario(
            name="Navigate directly from text and foreign-key fields",
            user=self.admin_user, url=todo.get_absolute_url(),
            actions=[e2e.E2EAction(execute=self.navigate_fields)],
        )]

    def navigate_fields(self):
        title = self.page.locator("#id_title")
        title.focus()
        title.press("ArrowRight")
        expect(title).to_be_focused()
        title.press("Shift+ArrowRight")
        expect(title).to_be_focused()
        title.press("Control+Alt+ArrowRight")
        expect(self.page.locator("#id_status")).to_be_focused()
        requested = self.page.locator('[bloomerp-component="foreign-field-widget"][data-field-name="requested_by"] input[type="text"]')
        assigned = self.page.locator('[bloomerp-component="foreign-field-widget"][data-field-name="assigned_to"] input[type="text"]')
        requested.focus()
        requested.fill(self.admin_user.get_username())
        dropdown = self.page.locator(".foreign-field-dropdown:visible")
        expect(dropdown).to_be_visible()
        requested.press("Control+Alt+ArrowRight")
        expect(assigned).to_be_focused()
        # Moving away must not choose a highlighted foreign-key result.
        expect(self.page.locator('[data-field-name="requested_by"] input[data-generated="true"]')).to_have_count(0)
