"""User lifecycle contracts for automatic staff inbox provisioning."""

from typing import Any
from unittest.mock import patch

from django.contrib.admin import AdminSite, ModelAdmin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.forms import modelform_factory
from django.test import RequestFactory, TestCase

from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.forms.model_form import BloomerpModelForm
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.tests.base import BloomerpModelTestCase, ModelScenario

User = get_user_model()


class TestUserModel(BloomerpModelTestCase):
    model = User

    def test_model_scenarios(self) -> None:
        """Simulate commit after each isolated save in the declarative scenarios.

        The shared runner wraps scenarios in rollback-only transactions. Keep
        its single-save validators while explicitly executing their callbacks;
        transaction-wide behavior is tested below without this adapter.
        """
        original_save = User.save

        def save_with_callbacks(
            user: AbstractBloomerpUser, *args: Any, **kwargs: Any
        ) -> None:
            """Persist a scenario save and execute callbacks at its simulated commit."""
            with self.captureOnCommitCallbacks(execute=True):
                original_save(user, *args, **kwargs)

        with patch.object(User, "save", save_with_callbacks):
            super().test_model_scenarios()

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


class TestUserInboxCommit(TestCase):
    """Exercise transaction boundaries separately from single-save scenarios."""

    def setUp(self) -> None:
        """Create two group-shared defaults and a non-staff recipient."""
        self.owner = User.objects.create(username="template-owner")
        self.user = User.objects.create(username="recipient")
        self.original_group = Group.objects.create(name="Original group")
        self.final_group = Group.objects.create(name="Final group")
        self.original_default = Inbox.objects.create(
            user=self.owner, name="Original default", initial_default=True
        )
        self.final_default = Inbox.objects.create(
            user=self.owner, name="Final default", initial_default=True
        )
        self.original_default.shared_with_groups.add(self.original_group)
        self.final_default.shared_with_groups.add(self.final_group)
        InboxFolder.objects.create(
            inbox=self.final_default, type="in_app_notifications"
        )

    def assert_final_default(self) -> None:
        """Require one independent selected copy of the final group default."""
        inbox = Inbox.objects.get(user=self.user)
        self.assertEqual(inbox.name, "Final default")
        self.assertTrue(inbox.selected)
        self.assertIsNone(inbox.source_object_id)
        self.assertCountEqual(
            inbox.folders.values_list("type", flat=True), ["in_app_notifications"]
        )

    def test_bloomerp_form_creates_with_group_default(self) -> None:
        """Staff creation and group assignment use the form's final defaults."""
        form_class = modelform_factory(
            User, form=BloomerpModelForm, fields=["username", "is_staff", "groups"]
        )
        form = form_class(
            {
                "username": "created-staff",
                "is_staff": True,
                "groups": [self.final_group.pk],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.captureOnCommitCallbacks(execute=True):
            self.user = form.save()
            self.assertFalse(Inbox.objects.filter(user=self.user).exists())
        self.assert_final_default()

    def test_deleted_user_does_not_provision(self) -> None:
        """A queued callback must tolerate deletion before the transaction commits."""
        user_pk = self.user.pk
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            self.user.is_staff = True
            self.user.save()
            self.user.delete()
        self.assertFalse(Inbox.objects.filter(user_id=user_pk).exists())

    def test_bloomerp_form_promotes_with_group_default(self) -> None:
        """The atomic application form must finish M2M writes before provisioning."""
        form_class = modelform_factory(
            User, form=BloomerpModelForm, fields=["is_staff", "groups"]
        )
        form = form_class(
            {"is_staff": True, "groups": [self.final_group.pk]}, instance=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.captureOnCommitCallbacks(execute=True):
            form.save()
            self.assertFalse(Inbox.objects.filter(user=self.user).exists())
        self.assert_final_default()

    def test_admin_save_uses_replacement_group(self) -> None:
        """An admin-style atomic save must use new groups rather than old membership."""
        self.user.groups.add(self.original_group)
        form_class = modelform_factory(User, fields=["is_staff", "groups"])
        form = form_class(
            {"is_staff": True, "groups": [self.final_group.pk]}, instance=self.user
        )
        self.assertTrue(form.is_valid(), form.errors)
        admin = ModelAdmin(User, AdminSite())
        request = RequestFactory().post("/admin/users/")
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            user = form.save(commit=False)
            admin.save_model(request, user, form, change=True)
            admin.save_related(request, form, [], change=True)
            self.assertFalse(Inbox.objects.filter(user=self.user).exists())
        self.assert_final_default()

    def test_repeated_saves_in_transaction_create_one_inbox(self) -> None:
        """All queued callbacks must recheck the final state and existing inbox."""
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            self.user.is_staff = True
            self.user.save()
            self.user.groups.set([self.final_group])
            self.user.save()
            self.user.save(update_fields=["first_name"])
            self.assertFalse(Inbox.objects.filter(user=self.user).exists())
        self.assert_final_default()

    def test_rolled_back_promotion_does_not_provision(self) -> None:
        """A savepoint rollback must discard its inbox provisioning callback."""
        with (
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            self.assertRaisesMessage(ValueError, "rollback"),
            transaction.atomic(),
        ):
            self.user.is_staff = True
            self.user.save()
            self.user.groups.add(self.final_group)
            raise ValueError("rollback")
        self.assertEqual(callbacks, [])
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(Inbox.objects.filter(user=self.user).exists())

    def test_final_nonstaff_state_does_not_provision(self) -> None:
        """A later demotion in the same transaction supersedes a queued promotion."""
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            self.user.is_staff = True
            self.user.save()
            self.user.is_staff = False
            self.user.save()
        self.assertFalse(Inbox.objects.filter(user=self.user).exists())

    def test_inbox_created_before_commit_is_preserved(self) -> None:
        """Keep a custom inbox created after the user save but before commit."""
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            self.user.is_staff = True
            self.user.save()
            inbox = Inbox.objects.create(user=self.user, name="Custom")
            Inbox.objects.filter(pk=inbox.pk).update(selected=False)
            folder = InboxFolder.objects.create(
                inbox=inbox, type="in_app_notifications"
            )
            self.user.groups.add(self.final_group)
        self.assertEqual(Inbox.objects.get(user=self.user).pk, inbox.pk)
        inbox.refresh_from_db()
        self.assertFalse(inbox.selected)
        self.assertEqual(list(inbox.folders.values_list("pk", flat=True)), [folder.pk])

    def test_shared_selection_created_before_commit_is_preserved(self) -> None:
        """Do not replace a selected shared reference with an initial-default copy."""
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            self.user.is_staff = True
            self.user.save()
            reference = Inbox.objects.create(
                user=self.user, source_object=self.original_default, selected=True
            )
            self.user.groups.add(self.final_group)
        inbox = Inbox.objects.get(user=self.user)
        self.assertEqual(inbox.pk, reference.pk)
        self.assertEqual(inbox.source_object_id, self.original_default.pk)
        self.assertTrue(inbox.selected)
