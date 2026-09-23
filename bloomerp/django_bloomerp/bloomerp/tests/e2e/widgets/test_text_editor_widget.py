"""Browser regressions for the rich text editor widget."""

from functools import partial

from django.urls import reverse
from django.utils.html import strip_tags
from playwright.sync_api import expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestTextEditorWidgetE2E(BloomerpE2ETestCase):
    """Check editor persistence and toolbar layout in a real browser."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe editor persistence and toolbar behavior at both screen widths."""
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
            ),
            E2ERequestScenario(
                name="Formatting toolbar stays within a phone viewport",
                user=self.admin_user,
                url=create_path,
                actions=self.toolbar_layout_actions(390),
            ),
            E2ERequestScenario(
                name="Formatting toolbar stays within a desktop viewport",
                user=self.admin_user,
                url=create_path,
                actions=self.toolbar_layout_actions(1280),
            ),
        ]

    def toolbar_layout_actions(self, width: int) -> list[E2EAction]:
        """Check default collapse, expansion, page width, and saved visibility."""
        return [
            E2EAction(
                name=f"Set viewport width to {width}px",
                execute=partial(self.set_editor_viewport, width),
                validators=self.expect_toolbar_hidden,
            ),
            E2EAction(
                name="Reveal formatting controls",
                execute=self.show_toolbar,
                validators=self.expect_toolbar_fits_page,
            ),
            E2EAction(
                name="Reload with visible toolbar preference",
                execute=self.reload_editor_page,
                validators=self.expect_toolbar_fits_page,
            ),
        ]

    def set_editor_viewport(self, width: int) -> None:
        """Resize the browser and dismiss the sidebar if it covers the editor."""
        self.page.set_viewport_size({"width": width, "height": 844})
        sidebar_overlay = self.page.locator("#sidebar-overlay")
        if sidebar_overlay.is_visible():
            sidebar_overlay.click()

    def expect_toolbar_hidden(self) -> None:
        """Check that the toolbar starts collapsed without a saved preference."""
        expect(self.page.locator('[data-text-editor-toolbar]')).to_be_hidden()
        expect(self.page.get_by_role("button", name="Show formatting toolbar")).to_be_visible()

    def show_toolbar(self) -> None:
        """Expand the editor formatting controls through the user-facing button."""
        self.page.get_by_role("button", name="Show formatting toolbar").click()

    def reload_editor_page(self) -> None:
        """Reload the form to verify the saved toolbar visibility choice."""
        self.page.reload(wait_until="domcontentloaded")

    def expect_toolbar_fits_page(self) -> None:
        """Check that a visible toolbar scrolls internally without widening the page."""
        toolbar = self.page.locator('[data-text-editor-toolbar]')
        expect(toolbar).to_be_visible()
        document_width = self.page.evaluate("document.documentElement.scrollWidth")
        viewport_width = self.page.evaluate("document.documentElement.clientWidth")
        toolbar_width = self.page.evaluate(
            "document.querySelector('[data-text-editor-toolbar]').clientWidth"
        )
        self.assertLessEqual(document_width, viewport_width)
        self.assertLessEqual(toolbar_width, viewport_width)

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
