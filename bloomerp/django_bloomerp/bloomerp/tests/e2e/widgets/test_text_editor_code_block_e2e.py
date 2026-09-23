import re

from django.urls import reverse
from playwright.sync_api import expect

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestTextEditorCodeBlockE2E(BloomerpE2ETestCase):
    """Check the code block's browser interaction and saved HTML contract."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe creation and persistence of a preformatted code block."""
        create_url = reverse(get_create_view_url(model=Todo))
        imported_todo = Todo.objects.create(
            title="Code block HTML import",
            content=(
                "<pre><code>first<br>second</code></pre>"
                "<pre><code><div>alpha</div><div>beta</div></code></pre>"
            ),
        )
        document_template = DocumentTemplate.objects.create(
            name="Unstyled code block",
            template="<pre><code>plain</code></pre>",
        )
        return [
            E2ERequestScenario(
                name="Code block preserves tabs and line breaks after saving",
                user=self.admin_user,
                url=create_url,
                actions=[
                    E2EAction(
                        name="Enter a title",
                        execute=self.input_field("title", "Code block persistence"),
                    ),
                    E2EAction(
                        name="Create and type in a code block",
                        execute=self.enter_code,
                        validators=self.check_editor_html,
                    ),
                    E2EAction(
                        name="Save the to-do",
                        execute=self.press_button_and_wait_for_response(
                            "Save",
                            create_url,
                            method="POST",
                        ),
                        validators=self.check_saved_code,
                    ),
                    E2EAction(
                        name="Open the saved to-do",
                        execute=self.open_saved_todo,
                        validators=self.check_rendered_code,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Slash command creates a code block",
                user=self.admin_user,
                url=create_url,
                actions=[
                    E2EAction(
                        name="Choose Code Block from the slash menu",
                        execute=self.enter_slash_code,
                        validators=self.check_slash_code_block,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="HTML line and block breaks survive code block import",
                user=self.admin_user,
                url=imported_todo.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Inspect imported code blocks",
                        execute=self.check_imported_markup_breaks,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Document template code blocks omit Bloomerp styling",
                user=self.admin_user,
                url=reverse(
                    "document_templates_detail_builder",
                    kwargs={"pk": document_template.pk},
                ),
                actions=[
                    E2EAction(
                        name="Inspect the template code block",
                        execute=self.check_template_code_styling,
                    ),
                ],
            ),
        ]

    def check_imported_markup_breaks(self) -> None:
        """Verify imported br and block elements become literal code newlines."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        expect(widget.locator("pre.bloomerp-text-editor-code-block")).to_have_count(2)
        field = widget.locator('input[name="content"]')
        expect(field).to_have_value(re.compile(r"first\nsecond.*alpha\nbeta", re.S))

    def check_template_code_styling(self) -> None:
        """Verify document-template code blocks do not use Bloomerp theme CSS."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="template"]'
        )
        expect(widget).to_have_attribute("data-override-default-styling", "True")
        code = widget.locator("pre").first
        expect(code).to_be_visible()
        expect(code).not_to_have_class(re.compile("bloomerp-text-editor-code-block"))

    def enter_slash_code(self) -> None:
        """Open the slash menu and select the code block action."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        editor = widget.locator('[contenteditable]')
        editor.click()
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        editor.type("/code")
        menu = self.page.locator("#bloomerp-text-editor-command-menu")
        menu.get_by_role("button", name="Code Block").click()

    def check_slash_code_block(self) -> None:
        """Assert the command removes its trigger and creates a code block."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        expect(widget.locator("pre.bloomerp-text-editor-code-block")).to_be_visible()
        expect(widget.locator('input[name="content"]')).to_have_value(
            '<pre data-text-editor-code-block="true"><code></code></pre>'
        )

    def enter_code(self) -> None:
        """Select the toolbar action and type code with a tab and newline."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        editor = widget.locator('[contenteditable]')
        editor.click()
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        widget.get_by_role("button", name="Show formatting toolbar").click()
        widget.get_by_role("button", name="Code Block").click()
        editor.type("if ready:")
        editor.press("Enter")
        editor.press("Tab")
        code_block = editor.locator("pre")
        expect(code_block).to_be_visible()
        code_block.click()
        code_block.press("End")
        self.page.keyboard.insert_text("run()")

    def check_editor_html(self) -> None:
        """Assert the form submits plain preformatted code with whitespace."""
        input_field = self.page.locator('input[name="content"]')
        expect(input_field).to_have_value(re.compile(r"run\(\)"))
        value = input_field.input_value()
        self.assertIn('<pre data-text-editor-code-block="true"><code>', value)
        self.assertIn("if ready:\n\trun()", value)

    def check_saved_code(self) -> None:
        """Assert the to-do stores the same code block in its HTML field."""
        todo = Todo.objects.get(title="Code block persistence")
        self.assertIn('<pre data-text-editor-code-block="true"><code>', todo.content)
        self.assertRegex(todo.content, r"if ready:\r?\n\trun\(\)")

    def open_saved_todo(self) -> None:
        """Navigate to the saved document's detail page."""
        todo = Todo.objects.get(title="Code block persistence")
        self.goto(todo.get_absolute_url())

    def check_rendered_code(self) -> None:
        """Assert the editor reimports the saved preformatted block."""
        widget = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        code = widget.locator('pre.bloomerp-text-editor-code-block')
        expect(code).to_be_visible()
        expect(code).to_contain_text("if ready:")
        expect(code).to_contain_text("run()")
        value = widget.locator('input[name="content"]').input_value()
        self.assertRegex(value, r"if ready:\r?\n\trun\(\)")
