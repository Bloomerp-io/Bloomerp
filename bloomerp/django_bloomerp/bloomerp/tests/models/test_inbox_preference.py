from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.communication.utils.permissions import (
    accessible_inbox_folders,
    accessible_inboxes,
)
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.models.communication.inbox.user_inbox_preference import (
    UserInboxPreference,
)
from bloomerp.services.preference_services import PreferenceManager


class InboxPreferenceTests(TestCase):
    def setUp(self) -> None:
        """Create inbox owners, viewers and folders for preference access checks."""
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="inbox-owner",
            email="inbox-owner@example.com",
            password="password",
        )
        self.viewer = user_model.objects.create_user(
            username="inbox-viewer",
            email="inbox-viewer@example.com",
            password="password",
        )
        self.outsider = user_model.objects.create_user(
            username="inbox-outsider",
            email="inbox-outsider@example.com",
            password="password",
        )
        self.inbox = Inbox.objects.create(
            user=self.owner,
            name="Support",
            selected=True,
        )
        self.folder = InboxFolder.objects.create(
            inbox=self.inbox,
            type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key,
        )

    def test_default_factory_creates_selected_inbox_and_default_folders(self) -> None:
        """Use case: Create an inbox. Expected result: Registered default folders are selected."""
        # 1. Create a default inbox for a new user.
        inbox = Inbox.create_default_for_user(self.outsider)

        # 2. Verify selection, ownership and registered folder defaults.
        self.assertTrue(inbox.selected)
        self.assertEqual(inbox.user, self.outsider)
        self.assertSetEqual(
            set(inbox.folders.values_list("type", flat=True)),
            {
                folder_type.key
                for folder_type in INBOX_FOLDER_REGISTRY.values()
                if folder_type.is_default
            },
        )

    def test_initial_default_is_copied_without_source_items(self):
        self.inbox.initial_default = True
        self.inbox.save(update_fields=["initial_default"])
        self.inbox.shared_with_users.add(self.viewer)
        InboxItem.objects.create(
            folder=self.folder,
            item_type=self.folder.inbox_folder_type().item_type.key,
            title="Source notification",
        )

        copied = PreferenceManager(self.viewer).get_or_create_selected(Inbox)

        self.assertEqual(copied.user, self.viewer)
        self.assertEqual(copied.name, self.inbox.name)
        self.assertTrue(copied.selected)
        self.assertIsNone(copied.source_object_id)
        self.assertSetEqual(
            set(copied.folders.values_list("type", flat=True)),
            {self.folder.type},
        )
        self.assertFalse(
            InboxItem.objects.filter(folder__inbox=copied).exists()
        )

    def test_named_inbox_copy_uses_requested_name_and_excludes_items(self):
        InboxItem.objects.create(
            folder=self.folder,
            item_type=self.folder.inbox_folder_type().item_type.key,
            title="Source notification",
        )

        copied = PreferenceManager(self.owner).create(
            Inbox,
            name="Personal",
        )

        self.assertEqual(copied.name, "Personal")
        self.assertEqual(copied.user, self.owner)
        self.assertIsNone(copied.source_object_id)
        self.assertSetEqual(
            set(copied.folders.values_list("type", flat=True)),
            {self.folder.type},
        )
        self.assertFalse(
            InboxItem.objects.filter(folder__inbox=copied).exists()
        )

    def test_direct_share_is_available_and_selects_live_source(self):
        self.inbox.shared_with_users.add(self.viewer)

        effective = PreferenceManager(self.viewer).select(self.inbox)

        reference = Inbox.objects.get(
            user=self.viewer,
            source_object=self.inbox,
        )
        self.assertTrue(reference.selected)
        self.assertEqual(effective, self.inbox)
        self.assertQuerySetEqual(
            accessible_inboxes(self.viewer),
            [self.inbox],
            transform=lambda inbox: inbox,
            ordered=False,
        )
        self.assertTrue(
            accessible_inbox_folders(self.viewer)
            .filter(pk=self.folder.pk)
            .exists()
        )

    def test_group_share_is_available_and_includes_group_members_as_recipients(self):
        group = Group.objects.create(name="Support team")
        group.user_set.add(self.viewer)
        self.inbox.shared_with_groups.add(group)

        self.assertTrue(
            accessible_inboxes(self.viewer).filter(pk=self.inbox.pk).exists()
        )
        self.assertSetEqual(
            set(self.folder.get_recipients().values_list("pk", flat=True)),
            {self.owner.pk, self.viewer.pk},
        )

    def test_revoking_share_removes_existing_reference_from_availability(self):
        self.inbox.shared_with_users.add(self.viewer)
        PreferenceManager(self.viewer).select(self.inbox)

        self.inbox.shared_with_users.remove(self.viewer)

        self.assertFalse(
            PreferenceManager(self.viewer)
            .get_available(Inbox)
            .filter(source_object=self.inbox)
            .exists()
        )
        self.assertIsNone(
            PreferenceManager(self.viewer).get_or_create_selected(
                Inbox,
                force_create=False,
            )
        )
        self.assertFalse(
            accessible_inbox_folders(self.viewer)
            .filter(pk=self.folder.pk)
            .exists()
        )

    def test_shared_user_can_select_folder_but_outsider_cannot(self):
        self.inbox.shared_with_users.add(self.viewer)
        PreferenceManager(self.viewer).select(self.inbox)
        url = reverse(
            "components_select_inbox_folder",
            kwargs={"folder_id": self.folder.pk},
        )

        self.client.force_login(self.viewer)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            UserInboxPreference.get_for_user(self.viewer).selected_inbox_folder,
            self.folder,
        )

        self.client.force_login(self.outsider)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 400)

    def test_folder_rendering_is_limited_to_available_inboxes(self):
        url = reverse(
            "components_render_inbox_folder_items",
            kwargs={"folder_id": self.folder.pk},
        )

        self.client.force_login(self.outsider)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        self.inbox.shared_with_users.add(self.viewer)
        self.client.force_login(self.viewer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_shared_user_cannot_add_or_delete_inbox_folders(self):
        self.inbox.shared_with_users.add(self.viewer)
        self.client.force_login(self.viewer)

        add_response = self.client.get(
            reverse(
                "components_add_inbox_folder",
                kwargs={"inbox_id": self.inbox.pk},
            )
        )
        delete_response = self.client.get(
            reverse(
                "components_execute_inbox_action",
                kwargs={
                    "level": "folder",
                    "item_id": self.folder.pk,
                    "action_key": "delete_inbox_folder",
                },
            )
        )

        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(InboxFolder.objects.filter(pk=self.folder.pk).exists())

    def test_inbox_view_renders_selected_effective_inbox(self) -> None:
        """Use case: Open a shared inbox. Expected result: Its effective folder is selected."""
        # 1. Select a shared inbox for a staff viewer.
        self.inbox.shared_with_users.add(self.viewer)
        PreferenceManager(self.viewer).select(self.inbox)
        self.viewer.is_staff = True
        self.viewer.save(update_fields=["is_staff"])
        self.client.force_login(self.viewer)

        # 2. Verify the effective inbox and folder context.
        response = self.client.get(reverse("inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["inbox"], self.inbox)
        self.assertEqual(
            response.context["inbox_preference"].selected_inbox_folder,
            self.folder,
        )

    def test_unread_counts_for_users_uses_one_query_and_resolves_shared_inbox(self):
        self.inbox.shared_with_users.add(self.viewer)
        PreferenceManager(self.viewer).select(self.inbox)
        item_type = self.folder.inbox_folder_type().item_type.key
        InboxItem.objects.bulk_create(
            [
                InboxItem(
                    folder=self.folder,
                    item_type=item_type,
                    title="Unread one",
                ),
                InboxItem(
                    folder=self.folder,
                    item_type=item_type,
                    title="Unread two",
                ),
                InboxItem(
                    folder=self.folder,
                    item_type=item_type,
                    title="Already read",
                    is_read=True,
                ),
            ]
        )
        user_model = get_user_model()
        expected = {
            str(self.owner.pk): 2,
            str(self.viewer.pk): 2,
            str(self.outsider.pk): 0,
        }

        with self.assertNumQueries(1):
            queryset_counts = Inbox.get_unread_count_for_users(
                user_model.objects.filter(
                    pk__in=[
                        self.owner.pk,
                        self.viewer.pk,
                        self.outsider.pk,
                    ]
                )
            )

        with self.assertNumQueries(1):
            list_counts = Inbox.get_unread_count_for_users(
                [
                    self.owner.pk,
                    self.viewer.pk,
                    self.outsider.pk,
                ]
            )

        with self.assertNumQueries(1):
            user_count = Inbox.get_unread_count_for_user(self.viewer)

        with self.assertNumQueries(1):
            user_without_inbox_count = Inbox.get_unread_count_for_user(
                self.outsider.pk
            )

        self.assertEqual(queryset_counts, expected)
        self.assertEqual(list_counts, expected)
        self.assertEqual(user_count, 2)
        self.assertEqual(user_without_inbox_count, 0)
