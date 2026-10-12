"""User lifecycle contracts for automatic staff inbox provisioning."""

from django.contrib.auth import get_user_model

from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario

User = get_user_model()


class TestUserModel(BloomerpModelTestCase):
    model = User

    def has_default_inbox(self, user: AbstractBloomerpUser) -> bool:
        """Require exactly one selected inbox with the registered default folders."""
        inbox = Inbox.objects.get(user=user)
        self.assertEqual(inbox.name, "My Inbox")
        self.assertTrue(inbox.selected)
        self.assertIsNone(inbox.source_object_id)
        self.assertCountEqual(
            inbox.folders.values_list("type", flat=True),
            [
                folder.key
                for folder in INBOX_FOLDER_REGISTRY.values()
                if folder.is_default
            ],
        )
        return True

    def has_no_inbox(self, user: AbstractBloomerpUser) -> bool:
        """Require non-staff and raw fixture creation to leave inboxes untouched."""
        return not Inbox.objects.filter(user=user).exists()

    def remember_inbox(self, user: AbstractBloomerpUser) -> None:
        """Record the automatically created inbox before another save."""
        self.inbox_id = Inbox.objects.get(user=user).pk

    def preserves_inbox(self, user: AbstractBloomerpUser) -> bool:
        """Require later saves to retain the same inbox and folder configuration."""
        self.assertEqual(Inbox.objects.get(user=user).pk, self.inbox_id)
        return self.has_default_inbox(user)

    def create_custom_inbox(self, user: AbstractBloomerpUser) -> None:
        """Create an intentionally unselected inbox before staff promotion."""
        self.existing = Inbox.objects.create(
            user=user, name="Custom inbox", selected=False
        )
        Inbox.objects.filter(pk=self.existing.pk).update(selected=False)
        self.folder = InboxFolder.objects.create(
            inbox=self.existing, type="in_app_notifications"
        )

    def preserves_custom_inbox(self, user: AbstractBloomerpUser) -> bool:
        """Keep an existing inbox unselected and preserve its exact folders."""
        inbox = Inbox.objects.get(user=user)
        self.assertEqual(inbox.pk, self.existing.pk)
        self.assertEqual(inbox.name, "Custom inbox")
        self.assertFalse(inbox.selected)
        self.assertEqual(
            list(inbox.folders.values_list("pk", flat=True)), [self.folder.pk]
        )
        return True

    def create_multiple_inboxes(self, user: AbstractBloomerpUser) -> None:
        """Prepare multiple personal inboxes with a deliberate selection."""
        self.first_inbox = Inbox.objects.create(user=user, name="First")
        self.selected_inbox = Inbox.objects.create(
            user=user, name="Selected", selected=True
        )

    def preserves_multiple_inboxes(self, user: AbstractBloomerpUser) -> bool:
        """Keep the full inbox set and its selected identity unchanged."""
        self.assertCountEqual(
            Inbox.objects.filter(user=user).values_list("pk", flat=True),
            [self.first_inbox.pk, self.selected_inbox.pk],
        )
        return Inbox.objects.get(user=user, selected=True).pk == self.selected_inbox.pk

    def promote_with_partial_save(self, user: AbstractBloomerpUser) -> None:
        """Persist staff promotion through the partial-save path used by forms."""
        user.is_staff = True
        user.save(update_fields=["is_staff"])

    def create_shared_selection(self, user: AbstractBloomerpUser) -> None:
        """Prepare an existing selected reference, even without a current share."""
        owner = User.objects.create(username="owner", email="owner@example.test")
        self.source = Inbox.objects.create(user=owner, name="Team inbox")
        self.existing = Inbox.objects.create(
            user=user, source_object=self.source, selected=True
        )

    def preserves_shared_selection(self, user: AbstractBloomerpUser) -> bool:
        """Do not replace, reselect, or duplicate existing shared preferences."""
        inbox = Inbox.objects.get(user=user)
        return (
            inbox.pk == self.existing.pk
            and inbox.selected
            and inbox.source_object_id == self.source.pk
        )

    def share_initial_default(self, user: AbstractBloomerpUser) -> None:
        """Share a configured initial default before promoting its recipient."""
        owner = User.objects.create(username="owner", email="owner@example.test")
        self.source = Inbox.objects.create(
            user=owner, name="Company inbox", initial_default=True
        )
        self.source.shared_with_users.add(user)
        InboxFolder.objects.create(inbox=self.source, type="in_app_notifications")

    def has_copied_initial_default(self, user: AbstractBloomerpUser) -> bool:
        """Reuse the preference manager's initial-default copy semantics."""
        inbox = Inbox.objects.get(user=user)
        self.assertEqual(inbox.name, "Company inbox")
        self.assertTrue(inbox.selected)
        self.assertIsNone(inbox.source_object_id)
        self.assertNotEqual(inbox.pk, self.source.pk)
        self.assertCountEqual(
            inbox.folders.values_list("type", flat=True), ["in_app_notifications"]
        )
        return True

    def create_raw_staff_user(self) -> AbstractBloomerpUser:
        """Simulate fixture loading without provisioning related records."""
        user = User(username="fixture", email="fixture@example.test", is_staff=True)
        user.save_base(raw=True)
        return user

    def save_unsaved_promotion(self, user: AbstractBloomerpUser) -> None:
        """Leave is_staff unsaved while persisting an unrelated field."""
        user.is_staff = True
        user.first_name = "Changed"
        user.save(update_fields=["first_name"])

    def save_unsaved_demotion(self, user: AbstractBloomerpUser) -> None:
        """Repair a persisted staff user despite an unsaved in-memory demotion."""
        user.is_staff = False
        user.first_name = "Changed"
        user.save(update_fields=["first_name"])

    def create_admin_user(self) -> AbstractBloomerpUser:
        """Exercise the standard superuser manager creation path."""
        return User.objects.create_superuser(
            username="admin", email="admin@example.test", password="test-only"
        )

    def get_test_scenarios(self) -> list[ModelScenario[AbstractBloomerpUser]]:
        """Cover creation, promotions, repairs, fixtures, and existing preferences."""
        return [
            ModelScenario(
                name="Superuser flag alone does not provision",
                create_args={"username": "nonstaff-admin", "is_superuser": True},
                create_validators=self.has_no_inbox,
            ),
            ModelScenario(
                name="Partial staff promotion provisions defaults",
                create_args={"username": "partial-promotion"},
                post_create=self.promote_with_partial_save,
                create_validators=self.has_default_inbox,
            ),
            ModelScenario(
                name="Multiple inboxes and selection are untouched",
                create_args={"username": "multiple"},
                post_create=self.create_multiple_inboxes,
                update_args={"is_staff": True},
                update_validators=self.preserves_multiple_inboxes,
            ),
            ModelScenario(
                name="Staff creation provisions defaults",
                create_args={"username": "staff", "is_staff": True},
                create_validators=self.has_default_inbox,
            ),
            ModelScenario(
                name="Non-staff creation and update do not provision",
                create_args={"username": "normal"},
                create_validators=self.has_no_inbox,
                update_args={"first_name": "Changed"},
                update_validators=self.has_no_inbox,
            ),
            ModelScenario(
                name="Superuser creation provisions defaults",
                create_operation=self.create_admin_user,
                create_validators=self.has_default_inbox,
            ),
            ModelScenario(
                name="Promotion provisions defaults",
                create_args={"username": "promotion"},
                create_validators=self.has_no_inbox,
                update_args={"is_staff": True},
                update_validators=self.has_default_inbox,
            ),
            ModelScenario(
                name="Repeated saves preserve defaults",
                create_args={"username": "repeat", "is_staff": True},
                post_create=self.remember_inbox,
                update_args={},
                update_validators=self.preserves_inbox,
            ),
            ModelScenario(
                name="Demotion preserves existing inbox",
                create_args={"username": "demote", "is_staff": True},
                post_create=self.remember_inbox,
                update_args={"is_staff": False},
                update_validators=self.preserves_inbox,
            ),
            ModelScenario(
                name="Existing unselected inbox is untouched",
                create_args={"username": "custom"},
                post_create=self.create_custom_inbox,
                update_args={"is_staff": True},
                update_validators=self.preserves_custom_inbox,
            ),
            ModelScenario(
                name="Existing shared selection is untouched",
                create_args={"username": "shared"},
                post_create=self.create_shared_selection,
                update_args={"is_staff": True},
                update_validators=self.preserves_shared_selection,
            ),
            ModelScenario(
                name="Promotion copies shared initial default",
                create_args={"username": "configured"},
                post_create=self.share_initial_default,
                update_args={"is_staff": True},
                update_validators=self.has_copied_initial_default,
            ),
            ModelScenario(
                name="Raw fixture skips provisioning and normal update repairs",
                create_operation=self.create_raw_staff_user,
                create_validators=self.has_no_inbox,
                update_args={"first_name": "Changed"},
                update_validators=self.has_default_inbox,
            ),
            ModelScenario(
                name="Unsaved promotion does not provision",
                create_args={"username": "unsaved"},
                post_create=self.save_unsaved_promotion,
                create_validators=self.has_no_inbox,
            ),
            ModelScenario(
                name="Unrelated partial save repairs persisted staff",
                create_operation=self.create_raw_staff_user,
                post_create=self.save_unsaved_demotion,
                create_validators=self.has_default_inbox,
            ),
        ]
