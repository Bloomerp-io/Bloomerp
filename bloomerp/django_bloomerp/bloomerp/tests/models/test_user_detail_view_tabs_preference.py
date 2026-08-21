import json
import uuid
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from bloomerp.models import Todo, User
from bloomerp.models.definition import DetailTab, DetailTabFolder, DetailViewSettings
from bloomerp.models.users.user_detail_view_tabs_preference import (
    UserDetailViewTabItem,
    UserDetailViewTabsPreference,
)
from bloomerp.services.preference_services import PreferenceManager


class UserDetailViewTabsPreferenceTests(TestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user(
            username="tabs-owner",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="tabs-other",
            password="testpass123",
        )
        self.content_type = ContentType.objects.get_for_model(Todo)

    def test_default_preference_uses_one_argument_detail_route_templates(self):
        """
        Use case: A user opens a model detail page without a tabs preference.
        Expected result: The default preference contains every one-PK detail route using {{pk}} URLs.
        """
        # 1. Create the default preference through the required BasePreference factory.
        preference = UserDetailViewTabsPreference.create_default_for_user(
            self.owner,
            content_type_id=self.content_type.pk,
        )

        # 2. Compare the relational tab items with the route catalog.
        options = UserDetailViewTabsPreference.get_detail_route_options(Todo)
        items = list(preference.items.exclude(url=None).order_by("position"))
        self.assertTrue(options)
        self.assertCountEqual(
            [(item.name, item.url) for item in items],
            [(option["name"], option["url"]) for option in options],
        )
        self.assertTrue(all("{{pk}}" in (item.url or "") for item in items))

        # 3. Confirm relationship routes are grouped instead of becoming base tabs.
        relationship_options = [
            option for option in options if option["is_relationship"]
        ]
        if relationship_options:
            folder = preference.items.get(name="Relationships", url=None)
            self.assertEqual(
                list(folder.children.values_list("url", flat=True)),
                [option["url"] for option in relationship_options],
            )

    def test_model_config_default_tabs_override_router_generated_tabs(self):
        """
        Use case: A model declares a custom default detail-tab layout.
        Expected result: The preference materializes only that ordered tab and folder tree.
        """
        # 1. Configure a custom top-level layout for the Todo model.
        detail_view_settings = DetailViewSettings(
            default_tabs=[
                DetailTab(name="Summary", url="/todos/{{pk}}/summary/"),
                DetailTabFolder(
                    name="Related work",
                    tabs=[
                        DetailTab(
                            name="Initiative",
                            url="/todos/{{pk}}/initiative/",
                        ),
                        DetailTab(
                            name="Dependencies",
                            url="/todos/{{pk}}/dependencies/",
                        ),
                    ],
                ),
                DetailTab(name="Documentation", url="https://docs.example.com/"),
            ]
        )

        # 2. Create the default preference while that model configuration is active.
        with patch.object(
            Todo.bloomerp_config,
            "detail_view_settings",
            detail_view_settings,
        ):
            preference = UserDetailViewTabsPreference.create_default_for_user(
                self.owner,
                content_type_id=self.content_type.pk,
            )

        # 3. Confirm exact top-level order and folder membership were materialized.
        top_level = list(
            preference.items.filter(parent=None).order_by("position", "id")
        )
        self.assertEqual(
            [(item.name, item.url, item.position) for item in top_level],
            [
                ("Summary", "/todos/{{pk}}/summary/", 0),
                ("Related work", None, 1),
                ("Documentation", "https://docs.example.com/", 2),
            ],
        )
        self.assertEqual(
            list(
                top_level[1].children.order_by("position", "id").values_list(
                    "name",
                    "url",
                    "position",
                )
            ),
            [
                ("Initiative", "/todos/{{pk}}/initiative/", 0),
                ("Dependencies", "/todos/{{pk}}/dependencies/", 1),
            ],
        )
        self.assertEqual(preference.items.count(), 5)

    def test_explicit_empty_model_config_default_tabs_create_no_items(self):
        """
        Use case: A model explicitly declares an empty default tab layout.
        Expected result: Router-derived tabs are suppressed and no items are created.
        """
        # 1. Configure an explicit empty override and create the preference.
        with patch.object(
            Todo.bloomerp_config,
            "detail_view_settings",
            DetailViewSettings(default_tabs=[]),
        ):
            preference = UserDetailViewTabsPreference.create_default_for_user(
                self.owner,
                content_type_id=self.content_type.pk,
            )

        # 2. Confirm the empty override did not fall back to router defaults.
        self.assertFalse(preference.items.exists())

    def test_preference_api_is_owner_scoped_and_items_are_not_exposed(self):
        """
        Use case: The preference selector renames an owned layout through the SDK.
        Expected result: Only owner-scoped preference fields are exposed, while item mutation stays component-only.
        """
        # 1. Read the explicit model API configurations.
        preference_api = UserDetailViewTabsPreference.bloomerp_config.api_settings
        item_api = UserDetailViewTabItem.bloomerp_config.api_settings

        # 2. Confirm the preference API is generated for authenticated owners.
        self.assertTrue(preference_api.enable_auto_generation)
        self.assertEqual(preference_api.user_access[0].through_field, "user")
        self.assertEqual(
            preference_api.user_access[0].field_actions["name"],
            ["view", "change"],
        )

        # 3. Confirm relational items remain behind the permission-aware components.
        self.assertFalse(item_api.enable_auto_generation)

    def test_folder_can_only_contain_tabs_from_the_same_preference(self):
        """
        Use case: Invalid folder trees are submitted programmatically.
        Expected result: Cross-preference children and nested folders are rejected.
        """
        # 1. Create two preferences and a valid folder.
        first = UserDetailViewTabsPreference.objects.create(
            user=self.owner,
            content_type=self.content_type,
        )
        second = UserDetailViewTabsPreference.objects.create(
            user=self.other_user,
            content_type=self.content_type,
        )
        folder = UserDetailViewTabItem.objects.create(
            preference=first,
            name="Related",
            url=None,
        )

        # 2. Validate that another preference cannot place a tab in that folder.
        cross_preference_tab = UserDetailViewTabItem(
            preference=second,
            parent=folder,
            name="Invalid",
            url="/todos/{{pk}}/",
        )
        with self.assertRaises(ValidationError):
            cross_preference_tab.full_clean()

        # 3. Validate that folders cannot be nested.
        nested_folder = UserDetailViewTabItem(
            preference=first,
            parent=folder,
            name="Nested",
            url=None,
        )
        with self.assertRaises(ValidationError):
            nested_folder.full_clean()

    def test_sync_tab_items_persists_order_folders_and_deletions(self):
        """
        Use case: The browser saves a drag-and-drop snapshot.
        Expected result: Positions, membership, edits, additions, and deletions are persisted atomically.
        """
        # 1. Create a preference containing an item that will be removed.
        preference = UserDetailViewTabsPreference.objects.create(
            user=self.owner,
            content_type=self.content_type,
        )
        removed = UserDetailViewTabItem.objects.create(
            preference=preference,
            name="Removed",
            url="/removed/",
        )
        folder_id = uuid.uuid4()
        tab_id = uuid.uuid4()

        # 2. Save a new folder tree snapshot.
        preference.sync_items(
            [
                {
                    "id": str(folder_id),
                    "name": "Relationships",
                    "url": None,
                    "parent_id": None,
                    "position": 0,
                },
                {
                    "id": str(tab_id),
                    "name": "Tasks",
                    "url": "/todos/{{pk}}/",
                    "parent_id": str(folder_id),
                    "position": 0,
                },
            ],
        )

        # 3. Confirm the old item is gone and the hierarchy is relational.
        self.assertFalse(UserDetailViewTabItem.objects.filter(pk=removed.pk).exists())
        folder = preference.items.get(pk=folder_id)
        tab = preference.items.get(pk=tab_id)
        self.assertTrue(folder.is_folder)
        self.assertEqual(tab.parent, folder)
        self.assertEqual(tab.position, 0)

    def test_new_named_preference_copies_the_relational_tree(self):
        """
        Use case: A user creates a named tabs preference from the selector.
        Expected result: The new independent preference receives a deep copy of the selected tree.
        """
        # 1. Create and select a source preference with a folder and child tab.
        source = UserDetailViewTabsPreference.objects.create(
            user=self.owner,
            content_type=self.content_type,
            selected=True,
        )
        folder = UserDetailViewTabItem.objects.create(
            preference=source,
            name="Folder",
            url=None,
        )
        UserDetailViewTabItem.objects.create(
            preference=source,
            parent=folder,
            name="Overview",
            url="/todos/{{pk}}/",
        )

        # 2. Create a named preference through the generic preference manager.
        copied = PreferenceManager(self.owner).create(
            UserDetailViewTabsPreference,
            name="Alternative",
            scope={"content_type_id": self.content_type.pk},
        )

        # 3. Confirm both rows were copied with new identities and preserved membership.
        copied_items = list(copied.items.order_by("parent_id", "position"))
        self.assertEqual(copied.name, "Alternative")
        self.assertEqual(len(copied_items), 2)
        copied_folder = next(item for item in copied_items if item.is_folder)
        copied_tab = next(item for item in copied_items if not item.is_folder)
        self.assertNotEqual(copied_folder.pk, folder.pk)
        self.assertEqual(copied_tab.parent, copied_folder)

    def test_rendered_items_resolve_only_the_primary_key_placeholder(self):
        """
        Use case: A stored URL is rendered for a concrete object.
        Expected result: {{pk}} resolves to that object's key and determines active navigation state.
        """
        # 1. Create a stored URL template.
        preference = UserDetailViewTabsPreference.objects.create(
            user=self.owner,
            content_type=self.content_type,
        )
        UserDetailViewTabItem.objects.create(
            preference=preference,
            name="Overview",
            url="/todos/{{pk}}/overview/",
        )

        # 2. Render the preference for object 42.
        rendered = preference.build_rendered_items(
            object_pk=42,
            request_path="/todos/42/overview/",
        )

        # 3. Confirm URL resolution and active state.
        self.assertEqual(rendered[0]["href"], "/todos/42/overview/")
        self.assertTrue(rendered[0]["is_active"])


class DetailTabsComponentTests(TestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user(
            username="component-tabs-owner",
            password="testpass123",
        )
        self.viewer = User.objects.create_user(
            username="component-tabs-viewer",
            password="testpass123",
        )
        self.content_type = ContentType.objects.get_for_model(Todo)
        self.preference = UserDetailViewTabsPreference.objects.create(
            user=self.owner,
            content_type=self.content_type,
            selected=True,
        )

    def test_owner_can_save_relational_tab_snapshot(self):
        """
        Use case: The owner reorders and creates items in the browser.
        Expected result: The component accepts and persists the complete snapshot.
        """
        # 1. Authenticate as the preference owner.
        self.client.force_login(self.owner)
        tab_id = uuid.uuid4()

        # 2. Submit a valid snapshot.
        response = self.client.post(
            reverse("components_detail_tabs_preference"),
            {
                "content_type_id": self.content_type.pk,
                "items": json.dumps(
                    [
                        {
                            "id": str(tab_id),
                            "name": "Overview",
                            "url": "/todos/{{pk}}/",
                            "parent_id": None,
                            "position": 0,
                        }
                    ]
                ),
            },
        )

        # 3. Confirm persistence.
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.preference.items.filter(pk=tab_id).exists())

    def test_generated_api_allows_only_the_owner_to_rename_preference(self):
        """
        Use case: The generic selector renames a tabs preference through the generated SDK.
        Expected result: The owner can change the name and another authenticated user cannot.
        """
        # 1. Rename through the same endpoint used by the generated SDK.
        endpoint = f"/api/user_detail_view_tabs_preferences/{self.preference.pk}/"
        self.client.force_login(self.owner)
        owner_response = self.client.patch(
            endpoint,
            data=json.dumps({"name": "Owner layout"}),
            content_type="application/json",
        )

        # 2. Confirm the owner-scoped update succeeded.
        self.assertEqual(owner_response.status_code, 200)
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.name, "Owner layout")

        # 3. Confirm another user cannot rename the owner's preference.
        self.client.force_login(self.viewer)
        viewer_response = self.client.patch(
            endpoint,
            data=json.dumps({"name": "Hijacked"}),
            content_type="application/json",
        )
        self.assertIn(viewer_response.status_code, {403, 404})
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.name, "Owner layout")

    def test_shared_preference_is_read_only_for_recipient(self):
        """
        Use case: A recipient selects a live shared tabs preference.
        Expected result: Mutation is denied because only the source owner may edit it.
        """
        # 1. Share and select the owner's preference for another user.
        self.preference.shared_with_users.add(self.viewer)
        PreferenceManager(self.viewer).select(self.preference)
        self.client.force_login(self.viewer)

        # 2. Attempt to overwrite the shared layout.
        response = self.client.post(
            reverse("components_detail_tabs_preference"),
            {
                "content_type_id": self.content_type.pk,
                "items": "[]",
            },
        )

        # 3. Confirm the permission-aware component rejects the write.
        self.assertEqual(response.status_code, 403)

    def test_url_modal_exposes_one_pk_route_datalist(self):
        """
        Use case: The owner creates a URL tab.
        Expected result: The modal exposes detail route templates and their names through a datalist.
        """
        # 1. Authenticate as the owner and request the create-URL form.
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("components_detail_tabs_item_modal"),
            {
                "content_type_id": self.content_type.pk,
                "item_type": "url",
                "mode": "create",
            },
        )

        # 2. Confirm the route datalist and supported placeholder are rendered.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<datalist id="detail-tab-route-options">', html=False)
        self.assertContains(response, "{{pk}}", html=False)
        self.assertContains(response, 'data-name="', html=False)

    def test_item_modal_uses_blank_form_and_emits_saved_event(self):
        """
        Use case: The owner creates a tab through the generic blank form.
        Expected result: The form posts to itself and emits the item payload without a custom success template.
        """
        # 1. Load the generic form fragment.
        self.client.force_login(self.owner)
        endpoint = reverse("components_detail_tabs_item_modal")
        response = self.client.get(
            endpoint,
            {
                "content_type_id": self.content_type.pk,
                "item_type": "url",
                "mode": "create",
            },
        )
        self.assertTemplateUsed(response, "utils/blank_form.html")
        self.assertContains(response, 'data-detail-tabs-item-form=""', html=False)

        # 2. Submit valid data and inspect the HTMX event payload.
        response = self.client.post(
            endpoint,
            {
                "content_type_id": self.content_type.pk,
                "item_type": "url",
                "mode": "create",
                "name": "Overview",
                "url": "/todos/{{pk}}/overview/",
            },
        )
        self.assertEqual(response.status_code, 204)
        event = json.loads(response.headers["HX-Trigger"])
        self.assertEqual(
            event["detail-tabs-item-saved"]["url"],
            "/todos/{{pk}}/overview/",
        )
