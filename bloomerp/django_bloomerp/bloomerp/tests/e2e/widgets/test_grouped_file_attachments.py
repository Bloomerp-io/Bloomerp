"""Browser contract for compact file groups and permission-aware attachment actions."""

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from playwright.sync_api import Response, expect

from bloomerp.models import FileNode, FileReference, Label, ObjectLabel
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import E2EAction, E2ERequestScenario
from bloomerp.tests.base.e2e_test_case import BloomerpE2ETestCase


class TestGroupedFileAttachments(BloomerpE2ETestCase):
    """Keep many attached files behind one tag without losing preview or editing."""

    auto_create_customers = False

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Exercise editable and read-only file groups against real stored attachments."""
        self.admin_user.is_staff = True
        self.admin_user.save(update_fields=["is_staff"])
        self.normal_user.is_staff = True
        self.normal_user.save(update_fields=["is_staff"])
        self.customer = self.create_customer("Grouped", "Files", 30)
        self.files = []
        for index in range(12):
            file = FileNode.objects.create(
                name=f"Document {index + 1}.txt",
                content=SimpleUploadedFile(f"document-{index + 1}.txt", b"Preview contents"),
                kind="FILE",
                created_by=self.admin_user,
            )
            FileReference.objects.create(file=file, content_object=self.customer)
            self.files.append(file)
        label = Label.objects.create(name="Other attachments", created_by=self.admin_user)
        ObjectLabel.objects.create(
            label=label,
            content_type=ContentType.objects.get_for_model(self.customer),
            object_id=str(self.customer.pk),
        )
        self.single_file_customer = self.create_customer("Single", "File", 30)
        FileReference.objects.create(file=self.files[0], content_object=self.single_file_customer)
        PolicyManager.create_policy(
            self.CustomerModel,
            row_permissions=[RowPolicyRuleContent(
                connector="AND", conditions=[], permissions=[BloomerpPermission.VIEW]
            )],
            field_permissions={"__all__": [BloomerpPermission.VIEW]},
        ).assign_user(self.normal_user)
        return [
            E2ERequestScenario(
                name="One files tag supports removal, undo, save, and preview",
                user=self.admin_user,
                url=self.customer.get_absolute_url(),
                actions=[E2EAction(name="Manage grouped attachments", execute=self.manage_files)],
            ),
            E2ERequestScenario(
                name="Read-only users can preview grouped files without removal controls",
                user=self.normal_user,
                url=self.customer.get_absolute_url(),
                prepare=self.restore_first_file,
                actions=[E2EAction(name="Inspect read-only file group", execute=self.inspect_read_only_files)],
            ),
            E2ERequestScenario(
                name="Removing the last file collapses the header and undo restores a closed group",
                user=self.admin_user,
                url=self.single_file_customer.get_absolute_url(),
                actions=[E2EAction(name="Remove and restore the last file", execute=self.remove_last_file)],
            ),
        ]

    def manage_files(self) -> None:
        """Remove one file, undo it, persist its removal, and open another file preview."""
        trigger = self.page.locator("[data-reference-files-trigger]")
        menu = self.page.locator("[data-reference-file-list]")
        expect(trigger).to_have_count(1)
        expect(trigger).to_have_text("Files (12)")
        expect(menu).to_be_hidden()
        expect(self.page.locator("[data-reference-chips]")).to_have_text("Other attachments×")
        trigger.click()
        expect(menu.get_by_role("menuitem")).to_have_count(12)
        menu.get_by_role("button", name="Remove Document 1.txt", exact=True).click()
        expect(trigger).to_have_text("Files (11)")
        self.assertEqual(FileReference.objects.filter(file=self.files[0], object_id=str(self.customer.pk)).count(), 1)
        self.page.locator("#object-crud-container-back-button").click()
        expect(trigger).to_have_text("Files (12)")
        trigger.click()
        menu.get_by_role("button", name="Remove Document 1.txt", exact=True).click()
        with self.page.expect_response(self.is_save_response):
            self.page.locator("#object-crud-container-save-button").click()
        self.page.wait_for_load_state("networkidle")
        self.assertFalse(FileReference.objects.filter(file=self.files[0], object_id=str(self.customer.pk)).exists())
        self.assertTrue(FileNode.objects.filter(pk=self.files[0].pk).exists())
        expect(trigger).to_have_text("Files (11)")
        trigger.click()
        self.preview_second_file()

    def inspect_read_only_files(self) -> None:
        """Ensure viewers retain previews and receive no controls for attachment mutation."""
        trigger = self.page.locator("[data-reference-files-trigger]")
        expect(trigger).to_have_text("Files (12)")
        expect(self.page.locator('[name="reference-attach"]')).to_have_count(0)
        trigger.click()
        expect(self.page.locator("[data-reference-file-list] [data-reference-remove]")).to_have_count(0)
        self.preview_second_file()

    def restore_first_file(self) -> None:
        """Give the read-only scenario a complete fixture independently of previous edits."""
        FileReference.objects.get_or_create(
            file=self.files[0],
            content_type=ContentType.objects.get_for_model(self.customer),
            object_id=str(self.customer.pk),
            application_field=None,
            occurrence_id=None,
        )

    def remove_last_file(self) -> None:
        """Hide an empty files group and restore it without reopening its dropdown."""
        trigger = self.page.locator("[data-reference-files-trigger]")
        expect(trigger).to_have_text("Files (1)")
        trigger.click()
        self.page.locator("[data-reference-file-list]").get_by_role("button", name="Remove Document 1.txt", exact=True).click()
        expect(trigger).to_be_hidden()
        expect(self.page.locator("[data-layout-header-section-2]")).to_be_hidden()
        self.page.locator("#object-crud-container-back-button").click()
        expect(trigger).to_have_text("Files (1)")
        expect(trigger).to_be_visible()
        expect(self.page.locator("[data-reference-file-list]")).to_be_hidden()

    def preview_second_file(self) -> None:
        """Open a grouped file through the existing shared preview drawer."""
        with self.page.expect_response(self.is_preview_response) as preview_response:
            self.page.locator("[data-reference-file-list]").get_by_role("menuitem", name="Document 2.txt", exact=True).click()
        self.assertEqual(preview_response.value.status, 200)
        expect(self.page.locator("#bloomerp-general-use-drawer-body")).to_contain_text("Preview contents")
        expect(self.page.locator("[data-reference-file-list]")).to_be_hidden()

    def is_save_response(self, response: Response) -> bool:
        """Match the detail form POST saving attachment changes for this customer."""
        return response.request.method == "POST" and str(self.customer.pk) in response.url

    def is_preview_response(self, response: Response) -> bool:
        """Match the preview response for the retained second file."""
        return "preview_file" in response.url and str(self.files[1].pk) in response.url
