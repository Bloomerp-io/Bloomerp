"""Browser regressions for rich-text heading hierarchy and persistence."""

import re

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url
from django.urls import reverse
from playwright.sync_api import Locator, expect


class TestTextEditorHeadingE2E(BloomerpE2ETestCase):
    """Verify heading sizes through import, conversion, saving, and opt-out."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe default heading hierarchy and custom styling behavior."""
        imported = Todo.objects.create(
            title="Legacy heading hierarchy",
            content='<h2 class="text-2xl font-bold mb-1">Section</h2>'
            '<h3 class="text-2xl font-bold">Subsection</h3>',
        )
        template = DocumentTemplate.objects.create(
            name="Unstyled headings",
            template="<h2>Section</h2><h3>Subsection</h3>",
        )
        create_url = reverse(get_create_view_url(model=Todo))
        return [
            E2ERequestScenario(
                name="Imported legacy H3 renders smaller than H2",
                user=self.admin_user,
                url=imported.get_absolute_url(),
                actions=[
                    E2EAction(name="Inspect heading sizes", execute=self.check_sizes)
                ],
            ),
            E2ERequestScenario(
                name="Converting H2 to H3 preserves the hierarchy after save and reload",
                user=self.admin_user,
                url=create_url,
                actions=[
                    E2EAction(
                        name="Name the to-do",
                        execute=self.input_field(
                            "title", "Heading hierarchy persistence"
                        ),
                    ),
                    E2EAction(
                        name="Create and convert headings", execute=self.enter_headings
                    ),
                    E2EAction(name="Inspect converted sizes", execute=self.check_sizes),
                    E2EAction(
                        name="Save the to-do",
                        execute=self.press_button_and_wait_for_response(
                            "Save", create_url, method="POST", expected_status=302
                        ),
                        validators=self.check_saved_headings,
                    ),
                    E2EAction(
                        name="Reopen saved headings",
                        execute=self.open_saved_todo,
                        validators=self.check_sizes,
                    ),
                    E2EAction(
                        name="Reload saved headings",
                        execute=self.reload_page,
                        validators=self.check_sizes,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Document-template headings keep their default-styling opt-out",
                user=self.admin_user,
                url=reverse(
                    "document_templates_detail_builder", kwargs={"pk": template.pk}
                ),
                actions=[
                    E2EAction(
                        name="Inspect unstyled headings",
                        execute=self.check_unstyled_headings,
                    )
                ],
            ),
        ]

    def content_widget(self) -> Locator:
        """Return the active to-do content editor widget."""
        return self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )

    def enter_headings(self) -> None:
        """Create two H2 blocks and convert the second into an H3 via the toolbar."""
        widget = self.content_widget()
        editor = widget.locator("[contenteditable]")
        editor.click()
        widget.get_by_role("button", name="Show formatting toolbar").click()
        widget.get_by_role("button", name="Heading 2", exact=True).click()
        self.page.keyboard.insert_text("Section")
        editor.press("Enter")
        widget.get_by_role("button", name="Heading 2", exact=True).click()
        self.page.keyboard.insert_text("Subsection")
        expect(editor.locator("h2")).to_have_count(2)
        widget.get_by_role("button", name="Heading 3", exact=True).click()
        expect(editor.locator("h2")).to_have_count(1)
        expect(editor.locator("h3")).to_have_count(1)

    def check_sizes(self) -> None:
        """Assert the real computed H3 font size is smaller than H2."""
        editor = self.content_widget().locator("[contenteditable]")
        h2 = editor.locator("h2")
        h3 = editor.locator("h3")
        expect(h2).to_have_text("Section")
        expect(h3).to_have_text("Subsection")
        h2_size = h2.evaluate(
            "element => parseFloat(getComputedStyle(element).fontSize)"
        )
        h3_size = h3.evaluate(
            "element => parseFloat(getComputedStyle(element).fontSize)"
        )
        self.assertGreater(h2_size, h3_size)
        expect(h2).to_have_class(re.compile(r"\btext-2xl\b"))
        expect(h3).to_have_class(re.compile(r"\btext-xl\b"))
        expect(h3).not_to_have_class(re.compile(r"\btext-2xl\b"))

    def check_saved_headings(self) -> None:
        """Check that submitted HTML preserves heading tags and distinct sizes."""
        todo = Todo.objects.get(title="Heading hierarchy persistence")
        self.assertRegex(todo.content, r'<h2[^>]*class="[^"]*text-2xl')
        self.assertRegex(todo.content, r'<h3[^>]*class="[^"]*text-xl')
        self.assertIn("Section", todo.content)
        self.assertIn("Subsection", todo.content)

    def open_saved_todo(self) -> None:
        """Reopen persisted HTML through the normal to-do detail view."""
        todo = Todo.objects.get(title="Heading hierarchy persistence")
        self.goto(todo.get_absolute_url())

    def reload_page(self) -> None:
        """Reload the page to reinitialize the editor from persisted content."""
        self.page.reload(wait_until="domcontentloaded")

    def check_unstyled_headings(self) -> None:
        """Ensure custom document styling does not acquire default heading classes."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="template"]'
        )
        expect(widget).to_have_attribute("data-override-default-styling", "True")
        for tag in ("h2", "h3"):
            heading = widget.locator(f"[contenteditable] {tag}")
            expect(heading).to_be_visible()
            expect(heading).not_to_have_class(re.compile(r"text-(?:2xl|xl)|font-bold"))
