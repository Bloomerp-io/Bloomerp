"""Browser regressions for the rich text editor widget."""

from functools import partial

from django.urls import reverse
from django.utils.html import strip_tags
from playwright.sync_api import Locator, expect

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
                name="Enter spaces paragraphs while Shift Enter stays within one paragraph",
                user=self.admin_user,
                url=create_path,
                actions=[
                    E2EAction(
                        name="Type a paragraph and a soft line break",
                        execute=self.type_paragraph_and_soft_break,
                        validators=self.expect_paragraph_spacing,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Checklist marker aligns with text and checks without a row outline",
                user=self.admin_user,
                url=create_path,
                actions=[
                    E2EAction(
                        name="Insert a checklist item",
                        execute=self.insert_checklist_item,
                        validators=self.expect_unchecked_checklist_item,
                    ),
                    E2EAction(
                        name="Check the marker",
                        execute=self.check_checklist_item,
                        validators=self.expect_checked_checklist_item,
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

    def type_paragraph_and_soft_break(self) -> None:
        """Enter a new paragraph followed by a line break within that paragraph."""
        editor = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] '
            '[contenteditable]'
        )
        editor.click()
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        editor.type("First paragraph")
        editor.press("Enter")
        self.page.keyboard.insert_text("Second line")
        editor.press("Shift+Enter")
        self.page.keyboard.insert_text("Same paragraph")

    def checklist_item(self) -> Locator:
        """Return the checklist item in the active text editor."""
        return self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] '
            'li[role="checkbox"]'
        )

    def insert_checklist_item(self) -> None:
        """Create a checklist item through the editor slash menu."""
        editor = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] '
            '[contenteditable]'
        )
        editor.click()
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        editor.type("/check")
        menu = self.page.locator("#bloomerp-text-editor-command-menu")
        menu.get_by_role("button", name="Checklist").click()
        self.page.keyboard.insert_text("Aligned item")

    def expect_unchecked_checklist_item(self) -> None:
        """Check the marker's compact text offset before toggling it."""
        item = self.checklist_item()
        expect(item).to_be_visible()
        expect(item).to_have_attribute("aria-checked", "false")
        expect(item).to_have_css("padding-left", "24px")

    def check_checklist_item(self) -> None:
        """Click the visible marker without focusing the entire checklist row."""
        self.checklist_item().click(position={"x": 8, "y": 12})

    def expect_checked_checklist_item(self) -> None:
        """Check primary color and absence of a mouse-triggered focus ring."""
        item = self.checklist_item()
        expect(item).to_have_attribute("aria-checked", "true")
        expect(item).to_have_css("outline-style", "none")
        marker_color = self.page.evaluate(
            "getComputedStyle(document.querySelector('li[role=\"checkbox\"]'), '::before').backgroundColor"
        )
        primary_color = self.page.evaluate(
            "getComputedStyle(document.querySelector('button.btn-primary')).backgroundColor"
        )
        self.assertEqual(marker_color, primary_color)
        marker_shadow = self.page.evaluate(
            "getComputedStyle(document.querySelector('li[role=\"checkbox\"]'), '::before').boxShadow"
        )
        self.assertEqual(marker_shadow, "none")

    def expect_paragraph_spacing(self) -> None:
        """Check that Enter adds a visible gap and Shift Enter adds only a br."""
        editor = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] '
            '[contenteditable]'
        )
        paragraphs = editor.locator("p")
        expect(paragraphs).to_have_count(2)
        expect(paragraphs.nth(1).locator("br")).to_have_count(1)
        expect(paragraphs.nth(1)).to_contain_text("Same paragraph")

        first_box = paragraphs.nth(0).bounding_box()
        second_box = paragraphs.nth(1).bounding_box()
        self.assertIsNotNone(first_box)
        self.assertIsNotNone(second_box)
        gap = second_box["y"] - (first_box["y"] + first_box["height"])
        self.assertGreaterEqual(gap, 6)

    def expect_saved_tab(self) -> None:
        """Verify that the database stores a tab between the typed words."""
        content = Todo.objects.get(title="Text editor tab regression").content
        self.assertIn("before\tafter", strip_tags(content))
        self.assertNotIn(".", content)
