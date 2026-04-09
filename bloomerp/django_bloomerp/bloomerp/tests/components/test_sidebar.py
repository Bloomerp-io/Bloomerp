from django.test import RequestFactory, TestCase

from bloomerp.components.workspaces.sidebar import (
    sidebar_create,
    sidebar_create_folder,
    sidebar_create_link_from_drop,
    sidebar_create_link,
    sidebar_edit_item,
    sidebar_delete_item,
    sidebar_delete,
    sidebar_move_item,
    sidebar_select_menu,
    sidebar_set_selected,
)
from bloomerp.models import Sidebar, SidebarItem, User
from bloomerp.models.workspaces.sidebar_item import (
    DEFAULT_FOLDER_ICON,
    DEFAULT_LINK_ICON,
)


class SidebarSelectionComponentTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="sidebar-user", password="testpass123")
        self.primary_sidebar = Sidebar.objects.create(user=self.user, name="Primary", selected=True)
        self.secondary_sidebar = Sidebar.objects.create(user=self.user, name="Secondary", selected=False)

    def test_selected_sidebar_creates_selected_default(self) -> None:
        user = User.objects.create_user(username="fresh-user", password="testpass123")

        sidebar = user.selected_sidebar

        self.assertTrue(sidebar.selected)
        self.assertEqual(user.sidebars.count(), 1)

    def test_sidebar_set_selected_marks_requested_sidebar_selected(self) -> None:
        request = self.factory.get(f"/components/workspaces/sidebar/select/{self.secondary_sidebar.id}/")
        request.user = self.user

        response = sidebar_set_selected(request, self.secondary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.primary_sidebar.refresh_from_db()
        self.secondary_sidebar.refresh_from_db()
        self.assertFalse(self.primary_sidebar.selected)
        self.assertTrue(self.secondary_sidebar.selected)
        self.assertContains(response, 'id="sidebar-content"', html=False)
        self.assertNotContains(response, "Current Sidebar")

    def test_sidebar_create_folder_get_renders_small_form(self) -> None:
        request = self.factory.get(f"/components/workspaces/sidebar/{self.primary_sidebar.id}/folders/create/")
        request.user = self.user

        response = sidebar_create_folder(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/components/workspaces/sidebar/1/folders/create/"', html=False)
        self.assertContains(response, 'name="name"', html=False)
        self.assertContains(response, f'name="icon" value="{DEFAULT_FOLDER_ICON}"', html=False)

    def test_sidebar_create_folder_post_creates_folder_and_refreshes_sidebar(self) -> None:
        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/folders/create/",
            {
                "name": "Operations",
            },
        )
        request.user = self.user

        response = sidebar_create_folder(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            SidebarItem.objects.filter(
                sidebar=self.primary_sidebar,
                name="Operations",
                is_folder=True,
                icon=DEFAULT_FOLDER_ICON,
            ).exists()
        )
        self.assertContains(response, 'hx-swap-oob="outerHTML"', html=False)
        self.assertEqual(response["HX-Trigger"], '{"dropdown-close": true}')

    def test_sidebar_create_subfolder_post_creates_child_folder(self) -> None:
        parent_item = SidebarItem.create_folder(self.primary_sidebar, "Parent")
        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/folders/create/",
            {
                "name": "Child",
                "icon": "fa-solid fa-folder",
                "parent_item_id": str(parent_item.id),
            },
        )
        request.user = self.user

        response = sidebar_create_folder(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            SidebarItem.objects.filter(sidebar=self.primary_sidebar, name="Child", parent=parent_item, is_folder=True).exists()
        )

    def test_sidebar_create_post_creates_sidebar_selects_it_and_refreshes_sidebar(self) -> None:
        request = self.factory.post(
            "/components/workspaces/sidebar/create/",
            {
                "name": "Operations",
            },
        )
        request.user = self.user

        response = sidebar_create(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Sidebar.objects.filter(user=self.user, name="Operations").exists())

        self.primary_sidebar.refresh_from_db()
        created_sidebar = Sidebar.objects.get(user=self.user, name="Operations")
        self.assertFalse(self.primary_sidebar.selected)
        self.assertTrue(created_sidebar.selected)
        self.assertContains(response, 'id="sidebar-content"', html=False)
        self.assertContains(response, 'hx-swap-oob="true"', html=False)
        self.assertEqual(response["HX-Trigger"], '{"dropdown-close": true}')

    def test_sidebar_select_menu_fetches_fresh_sidebar_list(self) -> None:
        Sidebar.objects.create(user=self.user, name="Fresh Sidebar", selected=False)
        request = self.factory.get("/components/workspaces/sidebar/select/")
        request.user = self.user

        response = sidebar_select_menu(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fresh Sidebar")

    def test_sidebar_create_link_post_creates_link(self) -> None:
        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/links/create/",
            {
                "name": "Docs",
                "url": "https://example.com/docs",
            },
        )
        request.user = self.user

        response = sidebar_create_link(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            SidebarItem.objects.filter(
                sidebar=self.primary_sidebar,
                name="Docs",
                url="https://example.com/docs",
                icon=DEFAULT_LINK_ICON,
            ).exists()
        )
        self.assertEqual(response["HX-Trigger"], '{"dropdown-close": true}')

    def test_sidebar_create_link_post_accepts_internal_path(self) -> None:
        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/links/create/",
            {
                "name": "Inbox",
                "url": "/inbox/",
            },
        )
        request.user = self.user

        response = sidebar_create_link(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        created_item = SidebarItem.objects.get(sidebar=self.primary_sidebar, name="Inbox")
        self.assertEqual(created_item.url, "/inbox/")
        self.assertTrue(created_item.is_internal_url)

    def test_sidebar_create_link_get_renders_link_default_icon(self) -> None:
        request = self.factory.get(f"/components/workspaces/sidebar/{self.primary_sidebar.id}/links/create/")
        request.user = self.user

        response = sidebar_create_link(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="icon" value="{DEFAULT_LINK_ICON}"', html=False)

    def test_sidebar_create_link_post_with_parent_item_creates_child_link(self) -> None:
        parent_item = SidebarItem.create_folder(self.primary_sidebar, "Parent")
        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/links/create/",
            {
                "name": "Docs",
                "icon": "fa-solid fa-link",
                "url": "https://example.com/docs",
                "parent_item_id": str(parent_item.id),
            },
        )
        request.user = self.user

        response = sidebar_create_link(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            SidebarItem.objects.filter(
                sidebar=self.primary_sidebar,
                name="Docs",
                url="https://example.com/docs",
                parent=parent_item,
            ).exists()
        )

    def test_sidebar_edit_item_get_renders_existing_folder_values(self) -> None:
        item = SidebarItem.create_folder(
            self.primary_sidebar,
            "Operations",
            icon=DEFAULT_FOLDER_ICON,
        )
        request = self.factory.get(f"/components/workspaces/sidebar/items/{item.id}/edit/")
        request.user = self.user

        response = sidebar_edit_item(request, item.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="/components/workspaces/sidebar/items/{item.id}/edit/"', html=False)
        self.assertContains(response, 'value="Operations"', html=False)
        self.assertContains(response, f'value="{DEFAULT_FOLDER_ICON}"', html=False)
        self.assertNotContains(response, 'name="url"', html=False)

    def test_sidebar_edit_item_post_updates_folder(self) -> None:
        item = SidebarItem.create_folder(self.primary_sidebar, "Operations", icon=DEFAULT_FOLDER_ICON)
        request = self.factory.post(
            f"/components/workspaces/sidebar/items/{item.id}/edit/",
            {
                "name": "Ops",
                "icon": DEFAULT_FOLDER_ICON,
            },
        )
        request.user = self.user

        response = sidebar_edit_item(request, item.id)

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.name, "Ops")
        self.assertEqual(item.icon, DEFAULT_FOLDER_ICON)
        self.assertTrue(item.is_folder)
        self.assertEqual(response["HX-Trigger"], '{"dropdown-close": true}')

    def test_sidebar_edit_item_post_updates_link(self) -> None:
        item = SidebarItem.create_link(
            self.primary_sidebar,
            "Docs",
            "https://example.com/docs",
            icon=DEFAULT_LINK_ICON,
        )
        request = self.factory.post(
            f"/components/workspaces/sidebar/items/{item.id}/edit/",
            {
                "name": "Inbox",
                "icon": DEFAULT_LINK_ICON,
                "url": "/inbox/",
            },
        )
        request.user = self.user

        response = sidebar_edit_item(request, item.id)

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.name, "Inbox")
        self.assertEqual(item.icon, DEFAULT_LINK_ICON)
        self.assertEqual(item.url, "/inbox/")
        self.assertTrue(item.is_internal_url)
        self.assertFalse(item.is_folder)

    def test_sidebar_renders_internal_links_as_htmx_navigation(self) -> None:
        SidebarItem.create_link(
            sidebar=self.primary_sidebar,
            name="Inbox",
            url="/inbox/",
        )
        request = self.factory.get(f"/components/workspaces/sidebar/select/{self.primary_sidebar.id}/")
        request.user = self.user

        response = sidebar_set_selected(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/inbox/"', html=False)
        self.assertContains(response, 'hx-get="/inbox/"', html=False)
        self.assertContains(response, 'hx-target="#main-content"', html=False)
        self.assertContains(response, 'hx-push-url="true"', html=False)

    def test_sidebar_renders_external_links_as_plain_links(self) -> None:
        SidebarItem.create_link(
            sidebar=self.primary_sidebar,
            name="Docs",
            url="https://example.com/docs",
        )
        request = self.factory.get(f"/components/workspaces/sidebar/select/{self.primary_sidebar.id}/")
        request.user = self.user

        response = sidebar_set_selected(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="https://example.com/docs"', html=False)
        self.assertContains(response, 'target="_blank"', html=False)
        self.assertContains(response, 'rel="noopener noreferrer"', html=False)
        self.assertNotContains(response, 'hx-get="https://example.com/docs"', html=False)

    def test_sidebar_delete_item_post_removes_item(self) -> None:
        item = SidebarItem.create_folder(self.primary_sidebar, "Delete Me")
        request = self.factory.post(f"/components/workspaces/sidebar/items/{item.id}/delete/")
        request.user = self.user

        response = sidebar_delete_item(request, item.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SidebarItem.objects.filter(pk=item.pk).exists())

    def test_sidebar_move_item_post_reorders_root_items(self) -> None:
        first = SidebarItem.create_link(self.primary_sidebar, "First", "https://example.com/first", position=0)
        second = SidebarItem.create_link(self.primary_sidebar, "Second", "https://example.com/second", position=1)
        third = SidebarItem.create_link(self.primary_sidebar, "Third", "https://example.com/third", position=2)

        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/items/move/",
            {
                "item_id": str(first.id),
                "position": "3",
            },
        )
        request.user = self.user

        response = sidebar_move_item(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        ordered_names = list(
            SidebarItem.objects.filter(sidebar=self.primary_sidebar, parent=None).order_by("position").values_list("name", flat=True)
        )
        self.assertEqual(ordered_names, ["Second", "Third", "First"])

    def test_sidebar_move_item_post_moves_item_into_folder(self) -> None:
        folder = SidebarItem.create_folder(self.primary_sidebar, "Folder", position=0)
        link = SidebarItem.create_link(self.primary_sidebar, "Docs", "https://example.com/docs", position=1)

        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/items/move/",
            {
                "item_id": str(link.id),
                "parent_item_id": str(folder.id),
                "position": "0",
            },
        )
        request.user = self.user

        response = sidebar_move_item(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.parent_id, folder.id)
        self.assertEqual(link.position, 0)

    def test_sidebar_move_item_post_moves_item_outside_folder(self) -> None:
        folder = SidebarItem.create_folder(self.primary_sidebar, "Folder", position=0)
        child = SidebarItem.create_link(
            self.primary_sidebar,
            "Docs",
            "https://example.com/docs",
            parent=folder,
            position=0,
        )
        SidebarItem.create_link(self.primary_sidebar, "Another", "https://example.com/another", position=1)

        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/items/move/",
            {
                "item_id": str(child.id),
                "position": "1",
            },
        )
        request.user = self.user

        response = sidebar_move_item(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertIsNone(child.parent)
        self.assertEqual(child.position, 1)

    def test_sidebar_move_item_post_rejects_moving_folder_into_descendant(self) -> None:
        parent_folder = SidebarItem.create_folder(self.primary_sidebar, "Parent", position=0)
        child_folder = SidebarItem.create_folder(self.primary_sidebar, "Child", parent=parent_folder, position=0)

        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/items/move/",
            {
                "item_id": str(parent_folder.id),
                "parent_item_id": str(child_folder.id),
                "position": "0",
            },
        )
        request.user = self.user

        response = sidebar_move_item(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 400)
        parent_folder.refresh_from_db()
        self.assertIsNone(parent_folder.parent)

    def test_sidebar_create_link_from_drop_post_creates_link_at_target_position(self) -> None:
        folder = SidebarItem.create_folder(self.primary_sidebar, "Folder", position=0)
        existing = SidebarItem.create_link(
            self.primary_sidebar,
            "Existing",
            "https://example.com/existing",
            parent=folder,
            position=0,
        )

        request = self.factory.post(
            f"/components/workspaces/sidebar/{self.primary_sidebar.id}/links/drop/",
            {
                "name": "Google",
                "url": "https://google.com/",
                "parent_item_id": str(folder.id),
                "position": "0",
            },
        )
        request.user = self.user

        response = sidebar_create_link_from_drop(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        ordered_names = list(
            SidebarItem.objects.filter(sidebar=self.primary_sidebar, parent=folder).order_by("position").values_list("name", flat=True)
        )
        self.assertEqual(ordered_names, ["Google", "Existing"])

    def test_sidebar_delete_post_selects_another_sidebar(self) -> None:
        request = self.factory.post(f"/components/workspaces/sidebar/delete/{self.primary_sidebar.id}/")
        request.user = self.user

        response = sidebar_delete(request, self.primary_sidebar.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Sidebar.objects.filter(pk=self.primary_sidebar.pk).exists())
        self.secondary_sidebar.refresh_from_db()
        self.assertTrue(self.secondary_sidebar.selected)
