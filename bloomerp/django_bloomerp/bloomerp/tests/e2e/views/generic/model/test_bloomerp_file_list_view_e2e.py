"""Browser navigation and uploads for virtual and physical file-node views."""

from urllib.parse import parse_qs, urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from playwright.sync_api import expect

from bloomerp.models.files.file_node import FileNode
from bloomerp.models.files.file_reference import FileReference
from bloomerp.models.project_management.todo import Todo
from bloomerp.modules.definition import module_registry
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_list_view_url


class TestBloomerpFileListViewE2E(BloomerpE2ETestCase):
    """Follow virtual folders, upload to an object, and switch physical hierarchies."""

    view_name = "app"
    auto_create_customers = False

    def prepare_files(self) -> None:
        """Create a referenced file in an existing physical folder."""
        self.todo = Todo.objects.create(title="Browser target")
        self.module = module_registry.get_module_for_model(Todo)
        self.folder = FileNode.objects.create(name="Stored documents", kind="FOLDER")
        self.file = FileNode.objects.create(
            name="Existing.pdf", kind="FILE", parent=self.folder,
            content=SimpleUploadedFile("existing.pdf", b"%PDF-sample"),
        )
        FileReference.objects.create(file=self.file, content_object=self.todo)

    def open_folder(self, name: str) -> None:
        """Wait for the navigation request and replacement browser before proceeding."""
        browser = self.page.locator('[bloomerp-component="file-browser"]')
        expect(browser).to_have_attribute("data-component-initialized", "true")
        with self.page.expect_response(lambda response: "components/" in response.url and "dataview" in response.url) as navigation:
            browser.get_by_role("button", name=name, exact=True).click()
        self.assertEqual(navigation.value.status, 200, navigation.value.text())
        expect(browser).to_be_visible()
        self.assertIn("data-folder-type", navigation.value.text(), navigation.value.url)

    def change_mode(self, mode: str) -> None:
        """Switch folder mode and verify that the opposite navigation token is cleared."""
        browser = self.page.locator('[bloomerp-component="file-browser"]')
        expect(browser).to_have_attribute("data-component-initialized", "true")
        self.page.locator('[data-file-browser-header] [data-folder-type-select]').select_option(mode)
        expect(browser).to_have_attribute("data-folder-type", mode)
        query = parse_qs(urlsplit(self.page.url).query)
        self.assertNotIn("virtual_path" if mode == "physical" else "folder_id", query)

    def upload_to_object(self) -> None:
        """Upload through the new API and verify the current virtual object's reference."""
        browser = self.page.locator('[bloomerp-component="file-browser"]')
        expect(browser).to_have_attribute("data-component-initialized", "true")
        with self.page.expect_response(lambda response: "/api/files/upload/" in response.url) as uploaded:
            self.page.locator('[data-file-browser-header] [data-file-browser-upload-input]').set_input_files({
                "name": "Uploaded.txt", "mimeType": "text/plain", "buffer": b"new bytes",
            })
        self.assertEqual(uploaded.value.status, 201)
        node = FileNode.objects.get(pk=uploaded.value.json()["file_id"])
        self.assertEqual(node.references.get().object_id, str(self.todo.pk))
        expect(browser.get_by_text("Uploaded.txt", exact=True)).to_be_visible()

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Exercise the folder hierarchy, upload destination, and mode-switch controls."""
        return [E2ERequestScenario(
            name="Virtual navigation and upload share content with physical browsing",
            user=self.admin_user, url=lambda: reverse(get_list_view_url(FileNode)), prepare=self.prepare_files,
            actions=[
                E2EAction(name="Open module", execute=lambda: self.open_folder(self.module.localized_name)),
                E2EAction(name="Open model", execute=lambda: self.open_folder(str(Todo._meta.verbose_name_plural))),
                E2EAction(name="Open object", execute=lambda: self.open_folder(str(self.todo))),
                E2EAction(name="Header contains current path and actions", execute=self.check_header),
                E2EAction(name="Upload to object", execute=self.upload_to_object),
                E2EAction(name="Navigate back using the header breadcrumb", execute=self.navigate_back),
                E2EAction(name="Switch to physical", execute=lambda: self.change_mode("physical")),
                E2EAction(name="Open existing physical folder", execute=lambda: self.open_folder(self.folder.name),
                    validators=lambda: expect(self.page.locator(f'[data-file-id="{self.file.pk}"]')).to_be_visible()),
                E2EAction(name="Switch back to virtual", execute=lambda: self.change_mode("virtual")),
            ],
        )]

    def check_header(self) -> None:
        """Keep navigation and actions inside the table header above the column headings."""
        header = self.page.locator("[data-file-browser-header]")
        expect(header.locator('[aria-current="page"]')).to_have_text(str(self.todo))
        expect(header.locator("[data-folder-type-select]")).to_have_count(1)
        expect(header.locator("[data-file-browser-upload-input]")).to_have_count(1)
        expect(self.page.locator('[bloomerp-component="file-browser"] thead [data-file-browser-header]')).to_have_count(1)

    def navigate_back(self) -> None:
        """Header breadcrumbs remain interactive after the upload refreshes the body."""
        header = self.page.locator("[data-file-browser-header]")
        header.get_by_role("button", name=str(Todo._meta.verbose_name_plural), exact=True).click()
        expect(header.locator('[aria-current="page"]')).to_have_text(str(Todo._meta.verbose_name_plural))
        expect(header.locator("[data-file-browser-upload-input]")).to_have_count(0)
        expect(header.locator("[data-folder-type-select]")).to_have_count(1)
