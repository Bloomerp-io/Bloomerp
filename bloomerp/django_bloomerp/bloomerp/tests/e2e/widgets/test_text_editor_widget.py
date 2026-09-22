"""Browser regressions for the rich text editor widget."""

from django.urls import reverse
from django.utils.html import strip_tags
from playwright.sync_api import expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestTextEditorWidgetE2E(BloomerpE2ETestCase):
    """Check that editor keystrokes survive a full form submission."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe the create form journey that persists an actual tab."""
        create_path = reverse(get_create_view_url(model=Todo))
        return [
            E2ERequestScenario(
                name="Tab in a text editor persists as a tab without dots",
                user=self.admin_user,
                url=create_path,
                actions=[
                    E2EAction(
                        name="Name the to-do",
                        execute=self.input_field("title", "Text editor tab regression"),
                    ),
                    E2EAction(
                        name="Type text around a tab",
                        execute=self.type_tab_in_editor,
                    ),
                    E2EAction(
                        name="Save and check stored content",
                        execute=self.press_button_and_wait_for_response(
                            "Save", create_path, method="POST", expected_status=302
                        ),
                        validators=self.expect_saved_tab,
                    ),
                ],
            )
        ]

    def type_tab_in_editor(self) -> None:
        """Enter text with a Tab keypress in the content editor."""
        editor = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] '
            '[contenteditable]'
        )
        expect(editor).to_be_visible()
        editor.click()
        editor.type("before")
        editor.press("Tab")
        editor.type("after")

    def expect_saved_tab(self) -> None:
        """Verify that the database stores a tab between the typed words."""
        content = Todo.objects.get(title="Text editor tab regression").content
        self.assertIn("before\tafter", strip_tags(content))
        self.assertNotIn(".", content)
