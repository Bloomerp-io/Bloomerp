"""Browser coverage of cursor-preserving template insertion in ordinary fields."""

from django.urls import reverse
from playwright.sync_api import expect
from bloomerp.models import DocumentTemplate
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestTextEditorTemplates(BloomerpE2ETestCase):
    """Check the shared command independently from email interception."""

    auto_create_customers = False

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Insert a template in the middle of ordinary editable content."""
        self.template = DocumentTemplate.objects.create(
            name="Reusable greeting", template="<p>Inserted {{ vars.name }}</p>",
        )
        return [E2ERequestScenario(
            name="Shared template insertion preserves surrounding text",
            user=self.admin_user, url=reverse(get_create_view_url(model=Todo)),
            actions=[
                E2EAction(name="Insert and edit a template", execute=self.insert_template),
                E2EAction(name="Replace selected text and navigate searchable submenus", execute=self.replace_selection),
            ],
        )]

    def insert_template(self) -> None:
        """Search, insert at a saved cursor, and preserve both surrounding content and source."""
        host = self.page.locator('[bloomerp-component="bloomerp-text-editor"]').first
        editor = host.locator("[contenteditable]")
        editor.fill("BeforeAfter")
        editor.press("Home")
        for _index in range(6):
            editor.press("ArrowRight")
        host.get_by_role("button", name="Show formatting toolbar").click()
        host.get_by_role("button", name="Template", exact=True).click()
        picker = self.page.get_by_role("group", name="Template", exact=True)
        picker.get_by_role("searchbox", name="Search templates").fill("Reusable")
        picker.get_by_role("button", name="Reusable greeting").click()
        expect(editor).to_contain_text("BeforeInserted {{ vars.name }}After")
        editor.fill("Edited copy")
        self.template.refresh_from_db()
        self.assertEqual(self.template.template, "<p>Inserted {{ vars.name }}</p>")


    def replace_selection(self) -> None:
        """Replace only a selected range and expose the same picker through slash commands."""
        host = self.page.locator('[bloomerp-component="bloomerp-text-editor"]').first
        editor = host.locator("[contenteditable]")
        editor.fill("BeforeReplaceAfter")
        editor.press("Home")
        for _index in range(6):
            editor.press("ArrowRight")
        for _index in range(7):
            editor.press("Shift+ArrowRight")
        host.get_by_role("button", name="Template", exact=True).click()
        picker = self.page.get_by_role("group", name="Template", exact=True)
        picker.get_by_role("button", name="Reusable greeting").click()
        expect(editor).to_contain_text("BeforeInserted {{ vars.name }}After")
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        editor.press_sequentially("/template")
        expect(editor).to_have_text("/template")
        self.page.locator("#bloomerp-text-editor-command-menu").get_by_role("button", name="Template").click()
        expect(picker).to_be_visible()
        picker.get_by_role("button", name="Reusable greeting").click()
        expect(editor).to_contain_text("Inserted {{ vars.name }}")
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        editor.press_sequentially("/template")
        expect(editor).to_have_text("/template")
        self.page.locator("#bloomerp-text-editor-command-menu").get_by_role("button", name="Template").click()
        picker.get_by_role("searchbox", name="Search templates").fill("no-match")
        expect(picker.get_by_text("No results.", exact=True)).to_be_visible()
        picker.get_by_role("button", name="Back", exact=True).click()
        menu = self.page.locator("#bloomerp-text-editor-command-menu")
        menu.get_by_role("button", name="Template", exact=True).click()
        search = picker.get_by_role("searchbox", name="Search templates")
        search.fill("Reusable")
        expect(picker.get_by_role("button", name="Reusable greeting")).to_be_visible()
        search.press("ArrowDown")
        search.press("Enter")
        expect(picker).not_to_be_visible()
        expect(editor).to_contain_text("Inserted {{ vars.name }}")
