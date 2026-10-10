"""Browser wiring for occurrence chips, editor removal, and saved manual labels."""

import base64

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from playwright.sync_api import Response, Route, expect

from bloomerp.models import (
    ApplicationField,
    FieldLayout,
    FileNode,
    FileReference,
    Label,
    LayoutItem,
    LayoutRow,
    Mention,
    ObjectLabel,
)
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_object_layout_preference import (
    UserObjectLayoutPreference,
)
from bloomerp.tests.base import E2EAction, E2ERequestScenario
from bloomerp.tests.base import e2e_test_case as e2e_test_cases
from bloomerp.utils.models import get_create_view_url


class TestEditorReferences(e2e_test_cases.BloomerpE2ETestCase):
    """Exercise real Lexical nodes and HTMX form state in the CRUD view."""

    auto_create_customers = False

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Insert repeated mentions, remove one occurrence, and persist a shared label."""
        self.admin_user.is_staff = True
        self.admin_user.first_name = "David"
        self.admin_user.last_name = "Bloomer"
        self.admin_user.save(update_fields=["is_staff", "first_name", "last_name"])
        Label.objects.create(name="Reference test", created_by=self.admin_user)
        Todo.objects.create(title="Object picker fixture")
        self.avatar_customer = self.create_customer("Avatar", "Hidden", 30)
        UserObjectLayoutPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            selected=True,
            layout=FieldLayout(
                rows=[
                    LayoutRow(
                        columns=1,
                        items=[
                            LayoutItem(
                                id=ApplicationField.get_by_field(
                                    self.CustomerModel, "first_name"
                                ).pk
                            )
                        ],
                    )
                ]
            ).model_dump(mode="json"),
        )
        return [
            E2ERequestScenario(
                name="Occurrence chips and manual labels save together",
                user=self.admin_user,
                url=reverse(get_create_view_url(model=Todo)),
                actions=[
                    E2EAction(
                        name="Empty attachment spacing and keyboard shortcut",
                        execute=self.check_attachment_controls,
                    ),
                    E2EAction(
                        name="Insert two mention occurrences",
                        execute=self.insert_mentions,
                    ),
                    E2EAction(
                        name="Remove exactly one occurrence",
                        execute=self.remove_occurrence,
                    ),
                    E2EAction(
                        name="Copy references and undo", execute=self.copy_and_undo
                    ),
                    E2EAction(
                        name="Attach a label and save", execute=self.attach_and_save
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Slash menus avoid a composer near the viewport bottom",
                user=self.admin_user,
                url=reverse(get_create_view_url(model=Todo)),
                actions=[
                    E2EAction(
                        name="Position slash menu and searchable submenu",
                        execute=self.check_slash_menu_position,
                    )
                ],
            ),
            E2ERequestScenario(
                name="Stored images persist without embedded bytes",
                user=self.admin_user,
                url=reverse(get_create_view_url(model=Todo)),
                actions=[
                    E2EAction(
                        name="Upload and save an image reference",
                        execute=self.upload_and_save_image,
                    )
                ],
            ),
            E2ERequestScenario(
                name="Avatar upload works outside the visible layout",
                user=self.admin_user,
                url=self.avatar_customer.get_absolute_url(),
                actions=[
                    E2EAction(
                        name="Select, undo, and save a hidden avatar",
                        execute=self.attach_hidden_avatar,
                    )
                ],
            ),
        ]

    def check_attachment_controls(self) -> None:
        """Check collapsed chips, shortcut opening, and grouped object search presentation."""
        component = self.page.locator('[bloomerp-component="reference-attachments"]')
        expect(component).to_be_hidden()
        expect(self.page.locator("[data-layout-header-section-2]")).to_be_hidden()
        button = self.page.locator('[name="reference-attach"]')
        expect(button.locator(".fa-paperclip")).to_have_count(1)
        expect(button.locator("svg")).to_have_count(0)
        self.assertTrue(button.get_attribute("aria-keyshortcuts"))
        self.page.keyboard.press("ControlOrMeta+Alt+T")
        expect(button).to_have_attribute("aria-expanded", "true")
        expect(
            self.page.get_by_role("menuitem", name="Labels", exact=True)
        ).to_be_visible()
        expect(
            self.page.get_by_role("menuitem", name="Upload file", exact=True)
        ).to_be_hidden()
        self.page.get_by_role("menuitem", name="Files", exact=True).click()
        panel = self.page.locator('[data-reference-search-panel="file"]')
        upload = panel.get_by_role("menuitem").first
        expect(upload).to_have_text("Upload file")
        expect(upload.locator(".fa-upload")).to_have_count(1)
        search_box = panel.get_by_role("searchbox").bounding_box()
        upload_box = upload.bounding_box()
        self.assertIsNotNone(search_box)
        self.assertIsNotNone(upload_box)
        self.assertGreaterEqual(upload_box["y"], search_box["y"] + search_box["height"])
        panel.get_by_role("searchbox").fill("no-matching-file")
        expect(panel.get_by_text("No results", exact=True)).to_be_visible()
        expect(panel.get_by_role("menuitem").first).to_have_text("Upload file")
        self.page.keyboard.press("Escape")
        self.page.get_by_role("menuitem", name="Objects", exact=True).click()
        self.page.get_by_role("searchbox", name="Search attachments").fill(
            "Object picker fixture"
        )
        result = self.page.get_by_role(
            "menuitem", name="Object picker fixture", exact=True
        )
        expect(result).to_be_visible()
        expect(result.locator("i")).to_have_count(1)
        expect(
            self.page.locator('[data-reference-results="object"]').get_by_text(
                str(Todo._meta.verbose_name_plural), exact=True
            )
        ).to_be_visible()
        self.page.keyboard.press("Escape")
        self.page.keyboard.press("Escape")
        expect(button).to_have_attribute("aria-expanded", "false")

    def insert_mentions(self) -> None:
        """Choose the same readable user twice and retain two independent chips."""
        self.assertTrue(
            self.page.locator('[name="title"]').count(),
            self.page.locator("body").inner_text(),
        )
        self.page.locator('[name="title"]').fill("Reference integration")
        host = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        editor = host.locator("[contenteditable]")
        editor.fill("Email person@example.com @")
        editor.press(" ")
        expect(editor).to_contain_text("person@example.com @")
        expect(editor.locator('[data-reference-kind="user"]')).to_have_count(0)
        expect(
            self.page.get_by_role("group", name="Mention suggestions", exact=True)
        ).to_be_hidden()
        editor.fill("Review ")
        host.get_by_role("button", name="Show formatting toolbar").click()
        for index in range(2):
            editor.click()
            editor.press("ControlOrMeta+End")
            if index == 0:
                editor.press("@")
                expect(editor).to_contain_text("Review @")
                expect(editor).to_be_focused()
                expect(
                    self.page.get_by_role("group", name="Mention", exact=True)
                ).to_be_hidden()
                editor.press("D")
                editor.press("a")
                editor.press("v")
                editor.press("i")
                editor.press("d")
                picker = self.page.get_by_role(
                    "group", name="Mention suggestions", exact=True
                )
                expect(picker).to_be_visible()
                expect(editor).to_be_focused()
                expect(editor).to_contain_text("Review @David")
                expect(picker.get_by_role("searchbox")).to_have_count(0)
                suggestion = picker.get_by_role(
                    "button", name="David Bloomer", exact=True
                )
                expect(suggestion).to_be_enabled()
                self.pending_mention_route: Route | None = None
                search_route = f"**{reverse('components_objects_references')}*"
                self.page.route(search_route, self.hold_mention_search)
                with self.page.expect_request(search_route):
                    editor.press("Backspace")
                expect(picker).to_be_visible()
                expect(picker).to_have_attribute("aria-busy", "true")
                expect(picker.locator(".fa-spinner")).to_be_visible()
                expect(suggestion).to_be_visible()
                expect(suggestion).to_be_disabled()
                assert self.pending_mention_route is not None
                self.pending_mention_route.continue_()
                self.page.unroute(search_route, self.hold_mention_search)
                expect(suggestion).to_be_enabled()
                editor.press("Escape")
                expect(picker).to_be_hidden()
                expect(editor).to_contain_text("Review @Davi")
                editor.press("Backspace")
            else:
                host.get_by_role("button", name="Mention", exact=True).click()
                picker = self.page.get_by_role("group", name="Mention", exact=True)
            expect(picker).to_be_visible()
            editor_box = editor.bounding_box()
            picker_box = picker.bounding_box()
            assert editor_box is not None and picker_box is not None
            self.assertLess(picker_box["y"], editor_box["y"] + 80)
            if index == 0:
                expect(
                    picker.get_by_role("button", name="David Bloomer", exact=True)
                ).to_be_enabled()
                editor.press("ArrowDown")
                editor.press("Enter")
            else:
                picker.get_by_role("button", name="David Bloomer", exact=True).click()
        expect(editor.locator('[data-reference-kind="user"]')).to_have_count(2)
        expect(
            self.page.locator("[data-reference-chips] [data-reference-remove]")
        ).to_have_count(2)
        expect(self.page.locator("[data-layout-header-section-2]")).to_be_visible()
        self.assertEqual(Mention.objects.count(), 0)

    def check_slash_menu_position(self) -> None:
        """Keep slash actions and reference search above the caret in a bottom composer."""
        host = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        host.evaluate(
            "element => { Object.assign(element.style, {position: 'fixed', bottom: '16px', left: '300px', width: '400px', height: '80px', zIndex: '40'}); }"
        )
        editor = host.locator("[contenteditable]")
        editor.evaluate(
            "element => { element.style.height = '60px'; element.style.minHeight = '60px'; }"
        )
        editor.click()
        editor.press("ControlOrMeta+A")
        editor.press("Backspace")
        editor.press_sequentially("/")
        expect(editor).to_have_text("/")
        menu = self.page.locator("#bloomerp-text-editor-command-menu")
        expect(menu).to_be_visible()
        labels = menu.locator("[data-context-menu-item]").all_text_contents()
        self.assertGreater(labels.index("Mention›"), labels.index("Table"))
        caret = editor.evaluate(
            "element => { const range = window.getSelection().getRangeAt(0).cloneRange(); range.setStart(range.endContainer, range.endOffset - 1); return range.getBoundingClientRect().top; }"
        )
        box = menu.bounding_box()
        self.assertIsNotNone(box)
        self.assertLessEqual(box["y"] + box["height"], caret - 7)
        menu.get_by_role("button", name="Mention", exact=False).click()
        expect(menu.get_by_role("searchbox")).to_be_visible()
        box = menu.bounding_box()
        self.assertIsNotNone(box)
        self.assertLessEqual(box["y"] + box["height"], caret - 7)
        self.page.keyboard.press("Escape")

    def attach_hidden_avatar(self) -> None:
        """Use the Attach avatar action without a visible cell and persist through normal Save."""
        avatar = self.page.locator("[data-reference-avatar-input]")
        expect(avatar).to_have_count(1)
        expect(avatar).to_be_hidden()
        self.page.locator('[name="reference-attach"]').click()
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role("menuitem", name="Avatar", exact=True).click()
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
        )
        selected_file = {"name": "avatar.png", "mimeType": "image/png", "buffer": image}
        chooser.value.set_files(selected_file)
        expect(self.page.locator("#object-crud-container-save-button")).to_be_visible()
        self.page.locator("#object-crud-container-back-button").click()
        self.assertEqual(avatar.evaluate("input => input.files.length"), 0)
        avatar.set_input_files(selected_file)
        with self.page.expect_response(self.is_avatar_save_response):
            self.page.locator("#object-crud-container-save-button").click()
        self.page.wait_for_load_state("networkidle")
        self.avatar_customer.refresh_from_db()
        self.assertTrue(self.avatar_customer.avatar.name.endswith(".png"))

    def is_avatar_save_response(self, response: Response) -> bool:
        """Recognize the update POST for the object whose avatar is being attached."""
        return (
            response.request.method == "POST"
            and str(self.avatar_customer.pk) in response.url
        )

    def hold_mention_search(self, route: Route) -> None:
        """Hold one search response so loading behavior can be asserted without timing races."""
        self.pending_mention_route = route

    def remove_occurrence(self) -> None:
        """Removing one chip removes only its corresponding editor token."""
        self.page.locator("[data-reference-remove]").first.click()
        editor = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] [contenteditable]'
        )
        expect(editor.locator('[data-reference-kind="user"]')).to_have_count(1)
        expect(self.page.locator("[data-reference-remove]")).to_have_count(1)

    def copy_and_undo(self) -> None:
        """Pasting generates a distinct occurrence and form undo restores the original."""
        editor = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"] [contenteditable]'
        )
        editor.click()
        editor.press("ControlOrMeta+A")
        editor.press("ControlOrMeta+C")
        editor.press("ArrowRight")
        self.assertEqual(self.page.evaluate("document.getSelection()?.toString()"), "")
        editor.press("ControlOrMeta+V")
        references = editor.locator('[data-reference-kind="user"]')
        expect(references).to_have_count(2)
        identities = references.evaluate_all(
            "nodes => nodes.map(node => node.dataset.occurrenceId)"
        )
        self.assertEqual(len(set(identities)), 2)
        editor.press("ControlOrMeta+Z")
        expect(references).to_have_count(1)
        expect(self.page.locator("[data-reference-remove]")).to_have_count(1)

    def attach_and_save(self) -> None:
        """Select a real label, submit the form, and verify both persisted relationships."""
        self.page.locator('[name="reference-attach"]').click()
        self.page.get_by_role("menuitem", name="Labels", exact=True).click()
        search = self.page.get_by_role("searchbox", name="Search attachments")
        search.fill("Reference")
        expect(
            self.page.get_by_role("menuitem", name="Reference test", exact=True)
        ).to_be_visible()
        search.press("ArrowDown")
        self.page.get_by_role("menuitem", name="Reference test", exact=True).press(
            "Enter"
        )
        expect(self.page.locator("[data-reference-chips]")).to_contain_text(
            "Reference test"
        )
        self.page.locator("#object-crud-container-back-button").click()
        expect(self.page.locator("[data-reference-chips]")).not_to_contain_text(
            "Reference test"
        )
        expect(self.page.locator("[data-reference-remove]")).to_have_count(1)
        self.page.locator('[name="reference-attach"]').click()
        self.page.get_by_role("menuitem", name="Labels", exact=True).click()
        self.page.get_by_role("menuitem", name="Reference test", exact=True).click()
        with self.page.expect_response(self.is_save_response):
            self.page.locator("#object-crud-container-save-button").click()
        self.page.wait_for_load_state("networkidle")
        todo = Todo.objects.get(title="Reference integration")
        self.assertEqual(Mention.objects.filter(object_id=str(todo.pk)).count(), 1)
        self.assertEqual(ObjectLabel.objects.filter(object_id=str(todo.pk)).count(), 1)
        self.assertIn("data-occurrence-id", todo.content)
        expect(self.page.locator("[data-reference-chips]")).to_contain_text(
            "Reference test"
        )

    def is_save_response(self, response: Response) -> bool:
        """Recognize the CRUD POST response without coupling the scenario to navigation."""
        return response.request.method == "POST" and "create" in response.url

    def upload_and_save_image(self) -> None:
        """Upload a file node and attach its editor occurrence after saving the parent."""
        self.page.locator('[name="title"]').fill("Stored image integration")
        host = self.page.locator(
            '[bloomerp-component="bloomerp-text-editor"][data-name="content"]'
        )
        editor = host.locator("[contenteditable]")
        editor.fill("Image reference")
        host.get_by_role("button", name="Show formatting toolbar").click()
        host.get_by_role("button", name="Image", exact=True).click()
        picker = self.page.get_by_role("group", name="Image", exact=True)
        with self.page.expect_file_chooser() as selection:
            picker.get_by_role("button", name="Upload image", exact=True).click()
        image = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
        )
        selection.value.set_files(
            {"name": "reference.png", "mimeType": "image/png", "buffer": image}
        )
        expect(editor.locator('img[src*="files/serve"]')).to_be_visible()
        expect(self.page.locator("[data-reference-chips]")).to_contain_text(
            "reference.png"
        )
        # Typing must continue in an editable paragraph after the image.
        self.page.keyboard.type("Text after the image")
        expect(editor.locator("figure + p")).to_have_text("Text after the image")
        self.page.keyboard.press("Enter")
        self.page.keyboard.type("Another paragraph")
        expect(editor.locator("figure + p + p")).to_have_text("Another paragraph")
        file = FileNode.objects.get(name="reference.png")
        self.assertFalse(file.references.exists())
        self.assertEqual(file.created_by_id, self.admin_user.pk)
        with self.page.expect_response(self.is_save_response):
            self.page.locator("#object-crud-container-save-button").click()
        self.page.wait_for_load_state("networkidle")
        todo = Todo.objects.get(title="Stored image integration")
        file.refresh_from_db()
        self.assertTrue(file.references.exists())
        self.assertEqual(
            FileReference.objects.filter(
                file=file, object_id=str(todo.pk)
            ).count(),
            1,
        )
        self.assertIn("data-reference-kind", todo.content)
        self.assertNotIn("data:image", todo.content)
        self.assertIn("Text after the image", todo.content)
        self.assertIn("Another paragraph", todo.content)
