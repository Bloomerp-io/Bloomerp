"""Attachment menu placement, color creation, and permission-scoped search journeys."""

from time import perf_counter

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.urls import reverse
from playwright.sync_api import Locator, expect

from bloomerp.models import FileNode, FileReference, Label
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestAttachmentMenuE2E(BloomerpE2ETestCase):
    """Exercise the actual dropdowns in transformed modals and authorized detail forms."""

    create_foreign_models = True
    auto_create_customers = False

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Cover modal geometry, searchable colors, and normal-user search requests."""
        self.customer = self.create_customer("Picker timing", "Owner", 30)
        file = FileNode.objects.create(kind="FILE", content=ContentFile(b"timing", name="Picker timing.txt"))
        FileReference.objects.create(file=file, content_object=self.customer)
        PolicyManager.create_policy(
            self.CustomerModel,
            row_permissions=[RowPolicyRuleContent(permissions=[BloomerpPermission.VIEW, BloomerpPermission.CHANGE])],
            field_permissions={"__all__": [BloomerpPermission.VIEW, BloomerpPermission.CHANGE]},
        ).assign_user(self.normal_user)
        return [
            E2ERequestScenario(
                name="Modal attachment menus stay anchored and create colored labels",
                user=self.admin_user,
                url=reverse(get_create_view_url(self.CustomerModel)),
                actions=[E2EAction(name="Create a colored label in the modal", execute=self.modal_color_picker)],
            ),
            E2ERequestScenario(
                name="Normal-user file and object dropdowns load authorized results",
                user=self.normal_user, url=self.customer.get_absolute_url(),
                actions=[E2EAction(name="Measure authorized dropdown searches", execute=self.measure_searches)],
            ),
        ]

    def modal_color_picker(self) -> None:
        """Keep viewport placement accurate and persist the selected searchable preset."""
        widget = self.page.locator('#main-content [data-field-name="country"][bloomerp-component="foreign-field-widget"]')
        widget.locator('input[type="text"]').focus()
        self.page.locator('.foreign-field-dropdown:visible [data-action="create-new"]').click()
        modal = self.page.locator('[data-modal-instance-of="create-object-modal"]')
        button = modal.locator('[name="reference-attach"]')
        expect(button).to_be_visible()
        button.click()
        menu = button.locator('..').locator(':scope > [data-dropdown-panel]')
        self.assert_anchored(button, menu, submenu=False)
        labels = modal.get_by_role("menuitem", name="Labels", exact=True)
        labels.click()
        submenu = labels.locator('..').locator(':scope > [data-dropdown-panel]')
        self.assert_anchored(labels, submenu, submenu=True)
        submenu.get_by_role("searchbox", name="Search attachments").fill("Golden modal label")
        create = submenu.locator('[data-reference-create-label]')
        expect(create).to_be_visible()
        create.click()
        colors = submenu.get_by_role("searchbox", name="Search colors", exact=True)
        colors.fill("Yellow")
        expect(submenu.locator('[data-reference-color]')).to_have_count(1)
        submenu.get_by_role("menuitem", name="Yellow", exact=True).click()
        chip = modal.locator('[data-reference-chips] .badge').filter(has_text="Golden modal label")
        expect(chip).to_be_visible()
        expect(chip).to_have_css("background-color", "rgb(250, 204, 21)")
        self.assertEqual(Label.objects.get(name="Golden modal label").color, "#facc15")
        expect(menu).to_be_hidden()

    def assert_anchored(self, trigger: Locator, panel: Locator, *, submenu: bool) -> None:
        """Compare settled menu bounds against their viewport-space trigger bounds."""
        expect(panel).to_be_visible()
        expect(panel).to_have_css("opacity", "1")
        self.assertTrue(panel.evaluate("element => element.matches(':popover-open')"))
        anchor = trigger.bounding_box()
        bounds = panel.bounding_box()
        self.assertIsNotNone(anchor)
        self.assertIsNotNone(bounds)
        if submenu:
            distance = min(abs(bounds["x"] - anchor["x"] - anchor["width"]), abs(bounds["x"] + bounds["width"] - anchor["x"]))
            self.assertLessEqual(distance, 10)
            self.assertLessEqual(abs(bounds["y"] - anchor["y"]), 10)
        else:
            self.assertLessEqual(abs(bounds["x"] - anchor["x"]), 2)
            self.assertLessEqual(abs(bounds["y"] - anchor["y"] - anchor["height"] - 8), 2)

    def measure_searches(self) -> None:
        """Record actual non-admin request latency and verify readable dropdown results."""
        button = self.page.locator('[name="reference-attach"]')
        for kind, name in (("file", "Files"), ("object", "Objects")):
            button.click()
            started = perf_counter()
            self.page.get_by_role("menuitem", name=name, exact=True).click()
            panel = self.page.locator(f'[data-reference-search-panel="{kind}"]')
            expect(panel.locator('[data-reference-results] button').first).to_be_visible()
            elapsed = perf_counter() - started
            print(f"Non-admin {kind} dropdown: {elapsed:.3f}s")
            self.assertLess(elapsed, 3.0)
            button.click()
            expect(button).to_have_attribute("aria-expanded", "false")
