from playwright.sync_api import Locator, expect

from bloomerp.models import Sidebar, SidebarItem
from bloomerp.tests.base import e2e_test_case as e2e


class TestSidebarE2E(e2e.BloomerpE2ETestCase):
    """Exercise persisted sidebar state and HTMX item updates in a real browser."""

    browser_context_options = {"viewport": {"width": 1364, "height": 998}}

    def get_test_scenarios(self) -> list[e2e.E2ERequestSetup]:
        return [
            e2e.E2ERequestSetup(
                name="Folder expansion is stored independently and restored",
                description=(
                    "Opening one folder must not open its sibling, and the choice "
                    "must survive a full page reload."
                ),
                user=self.admin_user,
                prepare=self.prepare_sidebar,
                url="/",
                actions=[
                    e2e.E2EAction(
                        name="Open one folder and reload the page",
                        execute=self.assert_folder_expansion_persists,
                    ),
                ],
            ),
            e2e.E2ERequestSetup(
                name="Item actions survive an HTMX save",
                description=(
                    "The action menu must escape the sidebar scroll container, and "
                    "saving an item must preserve both its controls and open state."
                ),
                user=self.admin_user,
                prepare=self.prepare_sidebar,
                url="/",
                actions=[
                    e2e.E2EAction(
                        name="Edit an expanded folder from its action menu",
                        execute=self.assert_item_actions_survive_save,
                    ),
                ],
            ),
        ]

    def prepare_sidebar(self) -> None:
        scenario_number = getattr(self, "_scenario_number", 0) + 1
        self._scenario_number = scenario_number
        self.sidebar = Sidebar.objects.create(
            user=self.admin_user,
            name=f"E2E sidebar {scenario_number}",
            selected=True,
        )
        self.primary_folder = SidebarItem.create_folder(
            self.sidebar,
            "Finance",
            position=0,
        )
        SidebarItem.create_link(
            self.sidebar,
            "Invoices",
            "/invoices/",
            parent=self.primary_folder,
            position=0,
        )
        self.secondary_folder = SidebarItem.create_folder(
            self.sidebar,
            "Projects",
            position=1,
        )
        SidebarItem.create_link(
            self.sidebar,
            "Roadmap",
            "/roadmap/",
            parent=self.secondary_folder,
            position=0,
        )

    def folder(self, item: SidebarItem) -> Locator:
        return self.page.locator(
            f'[data-sidebar-item-root][data-sidebar-item-id="{item.pk}"]'
        )

    def folder_children(self, item: SidebarItem) -> Locator:
        return self.folder(item).locator(":scope > [data-sidebar-children]")

    def open_folder(self, item: SidebarItem) -> None:
        self.folder(item).locator("[data-sidebar-folder-button]").click()
        expect(self.folder_children(item)).to_be_visible()
        expect(
            self.folder(item).locator("[data-sidebar-folder-button]")
        ).to_have_attribute("aria-expanded", "true")

    def assert_folder_expansion_persists(self) -> None:
        expect(self.folder_children(self.primary_folder)).to_be_hidden()
        expect(self.folder_children(self.secondary_folder)).to_be_hidden()

        self.open_folder(self.primary_folder)
        expect(self.folder_children(self.secondary_folder)).to_be_hidden()

        storage_key = f"bloomerp_sidebar_expanded_folders:{self.sidebar.pk}"
        self.assertEqual(
            self.page.evaluate("key => JSON.parse(localStorage.getItem(key))", storage_key),
            [str(self.primary_folder.pk)],
        )

        self.page.reload(wait_until="domcontentloaded")

        expect(self.folder_children(self.primary_folder)).to_be_visible()
        expect(self.folder_children(self.secondary_folder)).to_be_hidden()
        expect(
            self.folder(self.primary_folder).locator("[data-sidebar-folder-button]")
        ).to_have_attribute("aria-expanded", "true")

    def assert_item_actions_survive_save(self) -> None:
        self.open_folder(self.primary_folder)
        item = self.folder(self.primary_folder)
        item.hover()

        action_button = item.locator('button[aria-haspopup="true"]').first
        expect(action_button).to_be_visible()
        action_button.click()

        action_menu = item.locator(":scope > div .bloomerp-dropdown-menu").first
        expect(action_menu).to_be_visible()
        expect(action_menu).to_have_css("position", "fixed")
        self.assert_inside_viewport(action_menu)

        edit_path = f"/components/workspaces/sidebar/items/{self.primary_folder.pk}/edit/"
        with self.expect_response_for(edit_path, method="GET"):
            item.get_by_role("button", name="Edit", exact=True).click()

        edit_panel = self.page.locator(
            f"#sidebar-edit-item-panel-{self.primary_folder.pk}"
        )
        name_input = edit_panel.locator("#id_name")
        expect(name_input).to_be_visible()
        name_input.fill("Finance and Operations")

        with self.expect_response_for(edit_path, method="POST"):
            edit_panel.locator('button[type="submit"]').click()

        refreshed_item = self.folder(self.primary_folder)
        expect(refreshed_item).to_contain_text("Finance and Operations")
        expect(self.folder_children(self.primary_folder)).to_be_visible()

        refreshed_item.hover()
        expect(
            refreshed_item.locator('button[aria-haspopup="true"]').first
        ).to_be_visible()

        self.primary_folder.refresh_from_db()
        self.assertEqual(self.primary_folder.name, "Finance and Operations")

    def assert_inside_viewport(self, locator: Locator) -> None:
        box = locator.bounding_box()
        self.assertIsNotNone(box)
        viewport = self.page.viewport_size
        self.assertIsNotNone(viewport)
        assert box is not None and viewport is not None
        self.assertGreaterEqual(box["x"], 0)
        self.assertGreaterEqual(box["y"], 0)
        self.assertLessEqual(box["x"] + box["width"], viewport["width"])
        self.assertLessEqual(box["y"] + box["height"], viewport["height"])


class TestMobileSidebarE2E(e2e.BloomerpE2ETestCase):
    """Exercise touch behavior using the shared isolated browser context."""

    browser_context_options = {
        "viewport": {"width": 390, "height": 844},
        "has_touch": True,
        "is_mobile": True,
    }

    def get_test_scenarios(self) -> list[e2e.E2ERequestSetup]:
        return [
            e2e.E2ERequestSetup(
                name="A regular phone tap does not reveal the sidebar button",
                description=(
                    "Touching a page control away from the activation corner must "
                    "not reveal the floating sidebar control."
                ),
                user=self.admin_user,
                url="/",
                actions=[
                    e2e.E2EAction(
                        name="Tap a normal page control",
                        execute=self.assert_regular_tap_keeps_sidebar_button_hidden,
                    ),
                ],
            ),
        ]

    def assert_regular_tap_keeps_sidebar_button_hidden(self) -> None:
        self.page.evaluate(
            """
            () => {
                const button = document.createElement('button');
                button.textContent = 'Phone action';
                button.style.position = 'fixed';
                button.style.left = '160px';
                button.style.top = '300px';
                button.addEventListener('click', () => button.dataset.clicked = 'true');
                document.body.appendChild(button);
            }
            """
        )
        action_button = self.page.get_by_role("button", name="Phone action")

        action_button.tap()

        expect(action_button).to_have_attribute("data-clicked", "true")
        expect(self.page.locator("#sidebar-toggle-floating")).to_be_hidden()
