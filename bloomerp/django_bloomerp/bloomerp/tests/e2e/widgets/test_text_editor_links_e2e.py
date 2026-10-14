"""Exercise link insertion through the real editor toolbar, clipboard and form."""

import re

from django.urls import reverse
from playwright.sync_api import Locator, expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestTextEditorLinksE2E(BloomerpE2ETestCase):
    """Verify links persist and dialog dismissal leaves editor content intact."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe paste persistence and repeatable named-link interactions."""
        create_url = reverse(get_create_view_url(model=Todo))
        return [
            E2ERequestScenario(
                name="Pasted URL survives save and reload as a link",
                user=self.admin_user,
                url=create_url,
                actions=[
                    E2EAction(
                        name="Enter a title",
                        execute=self.input_field("title", "Link paste persistence"),
                    ),
                    E2EAction(name="Paste a URL", execute=self.paste_url),
                    E2EAction(
                        name="Save the to-do",
                        execute=self.press_button_and_wait_for_response(
                            "Save", create_url, method="POST"
                        ),
                        validators=self.check_saved_link,
                    ),
                    E2EAction(
                        name="Reload saved content",
                        execute=self.open_saved_todo,
                        validators=self.check_pasted_link,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Named links support validation, cancellation and repeated insertion",
                user=self.admin_user,
                url=create_url,
                actions=[
                    E2EAction(
                        name="Cancel and reopen the link form",
                        execute=self.cancel_and_reopen,
                    ),
                    E2EAction(
                        name="Reject an unsafe URL and insert a named link",
                        execute=self.insert_named_link,
                    ),
                    E2EAction(
                        name="Insert another link and undo then redo",
                        execute=self.repeat_and_undo,
                    ),
                ],
            ),
        ]

    def widget(self) -> Locator:
        """Locate only the to-do content editor, excluding comment editors."""
        return self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )

    def paste_url(self) -> None:
        """Dispatch a browser ClipboardEvent, the shared Cmd/Ctrl+V paste path."""
        editor = self.widget().locator("[contenteditable]")
        editor.click()
        editor.evaluate(
            """element => {
                const data = new DataTransfer();
                data.setData('text/plain', 'https://example.com/docs?q=links');
                element.dispatchEvent(new ClipboardEvent('paste', {
                    clipboardData: data, bubbles: true, cancelable: true
                }));
            }"""
        )
        self.check_pasted_link()

    def check_pasted_link(self) -> None:
        """Check destination, name and default visual styling in the editor."""
        link = self.widget().locator('a[href="https://example.com/docs?q=links"]')
        expect(link).to_have_text("https://example.com/docs?q=links")
        expect(link).to_have_class(re.compile(r"text-blue-600.*underline"))
        expect(link).to_have_css("text-decoration-line", "underline")

    def check_saved_link(self) -> None:
        """Assert the database stores a real anchor rather than only raw URL text."""
        todo = Todo.objects.get(title="Link paste persistence")
        self.assertIn('href="https://example.com/docs?q=links"', todo.content)
        self.assertIn("<a ", todo.content)

    def open_saved_todo(self) -> None:
        """Open the newly saved fixture through its normal detail URL."""
        self.goto(Todo.objects.get(title="Link paste persistence").get_absolute_url())

    def cancel_and_reopen(self) -> None:
        """Preserve selected text across Cancel and a second toolbar invocation."""
        editor = self.widget().locator("[contenteditable]")
        editor.click()
        editor.type("BloomERP")
        editor.press("ControlOrMeta+A")
        self.widget().get_by_role("button", name="Show formatting toolbar").click()
        self.widget().get_by_role("button", name="Link", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="Insert link", exact=True)
        expect(dialog.get_by_label("Link name", exact=True)).to_have_value("BloomERP")
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(editor).to_have_text("BloomERP")
        expect(editor.locator("a")).to_have_count(0)
        editor.click()
        editor.press("ControlOrMeta+A")
        self.widget().get_by_role("button", name="Link", exact=True).click()

    def insert_named_link(self) -> None:
        """Keep invalid destinations out of the document, then apply a safe one."""
        dialog = self.page.get_by_role("dialog", name="Insert link", exact=True)
        dialog.get_by_label("Link URL", exact=True).fill("javascript:alert(1)")
        dialog.get_by_role("button", name="Insert link", exact=True).click()
        expect(dialog).to_be_visible()
        expect(self.widget().locator("a")).to_have_count(0)
        dialog.get_by_label("Link URL", exact=True).fill("https://bloomerp.io")
        dialog.get_by_role("button", name="Insert link", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(self.widget().locator('a[href="https://bloomerp.io"]')).to_have_text("BloomERP")

    def repeat_and_undo(self) -> None:
        """Insert a second independent link and validate its undo/redo history."""
        editor = self.widget().locator("[contenteditable]")
        editor.click()
        editor.press("ControlOrMeta+End")
        editor.press("ArrowRight")
        editor.type(" ")
        self.widget().get_by_role("button", name="Link", exact=True).click()
        dialog = self.page.get_by_role("dialog", name="Insert link", exact=True)
        dialog.get_by_label("Link name", exact=True).fill("Documentation")
        dialog.get_by_label("Link URL", exact=True).fill("https://example.com/docs")
        dialog.get_by_role("button", name="Insert link", exact=True).click()
        expect(editor.locator("a")).to_have_count(2)
        editor.press("ControlOrMeta+z")
        expect(editor.locator("a")).to_have_count(1)
        editor.press("ControlOrMeta+Shift+z")
        expect(editor.locator("a")).to_have_count(2)
        expect(editor.locator("a a")).to_have_count(0)
