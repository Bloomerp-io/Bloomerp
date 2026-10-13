import inspect

from django.apps import apps
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction

from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.base_preference import BasePreference
from bloomerp.models.workspaces.sidebar import Sidebar
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.services.preference_services import PreferenceManager, clean_scope
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class PreferenceManagerTestCase(BaseBloomerpTestCaseWithModels):
    auto_create_customers = False

    def extendedSetup(self):
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.scope = {"content_type_id": self.content_type.pk}
        self.manager = PreferenceManager(self.admin_user)

    def test_clean_scope_parses_none_and_boolean_values(self):
        scope = {
            "python_none": None,
            "string_none": " None ",
            "string_null": "NULL",
            "enabled": " TrUe ",
            "disabled": "FALSE",
            "content_type_id": str(self.content_type.pk),
        }

        result = clean_scope(scope)

        self.assertEqual(
            result,
            {
                "python_none": None,
                "string_none": None,
                "string_null": None,
                "enabled": True,
                "disabled": False,
                "content_type_id": str(self.content_type.pk),
            },
        )
        self.assertEqual(scope["enabled"], " TrUe ")

    def test_every_concrete_preference_implements_abstract_contract(self):
        self.assertTrue(inspect.isabstract(BasePreference))
        concrete_preferences = [
            model
            for model in apps.get_models()
            if issubclass(model, BasePreference) and not model._meta.abstract
        ]

        self.assertTrue(concrete_preferences)
        self.assertEqual(
            [
                model.__name__
                for model in concrete_preferences
                if inspect.isabstract(model)
            ],
            [],
        )

    def test_normalize_scope_preserves_explicit_none(self):
        self.assertEqual(Sidebar.normalize_scope({}), {})
        self.assertEqual(
            Workspace.normalize_scope({"module_id": None}),
            {"module_id": None},
        )

    def test_get_or_create_selected_returns_existing_selection(self):
        selected = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Existing",
            selected=True,
        )

        result = self.manager.get_or_create_selected(
            UserListViewPreference,
            self.scope,
        )

        self.assertEqual(result, selected)
        self.assertEqual(
            UserListViewPreference.objects.filter(user=self.admin_user).count(),
            1,
        )

    def test_group_selection_falls_back_after_membership_is_revoked(self) -> None:
        """
        Use case: A selected shared preference becomes unavailable after group membership ends.
        Expected result: The live source is used while shared, then an owned preference is selected.
        """
        # 1. Select a group-shared source for an ordinary user with an owned fallback.
        manager = PreferenceManager(self.normal_user)
        owned = UserListViewPreference.objects.create(
            user=self.normal_user, content_type=self.content_type, name="Owned fallback"
        )
        source = UserListViewPreference.objects.create(
            user=self.admin_user, content_type=self.content_type, name="Group view"
        )
        group = Group.objects.create(name="Selected preference group")
        group.user_set.add(self.normal_user)
        source.shared_with_groups.add(group)
        manager.select(source)
        self.assertEqual(
            manager.get_or_create_selected(UserListViewPreference, self.scope), source
        )
        # 2. Revoke membership without deleting the stored reference.
        group.user_set.remove(self.normal_user)
        self.assertTrue(
            UserListViewPreference.objects.filter(
                user=self.normal_user, source_object=source
            ).exists()
        )
        # 3. Resolve the remaining owned preference rather than the revoked source.
        self.assertEqual(
            manager.get_or_create_selected(UserListViewPreference, self.scope), owned
        )
        owned.refresh_from_db()
        self.assertTrue(owned.selected)

    def test_get_or_create_selected_selects_existing_unselected_preference(self):
        existing = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Existing",
        )
        UserListViewPreference.objects.filter(pk=existing.pk).update(selected=False)

        result = self.manager.get_or_create_selected(
            UserListViewPreference,
            self.scope,
        )

        existing.refresh_from_db()
        self.assertEqual(result, existing)
        self.assertTrue(existing.selected)

    def test_get_or_create_selected_references_shared_initial_default(self):
        shared_default = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            name="Company default",
            initial_default=True,
        )
        shared_default.shared_with_users.add(self.admin_user)

        result = self.manager.get_or_create_selected(
            UserListViewPreference,
            self.scope,
        )

        reference = UserListViewPreference.objects.get(
            user=self.admin_user,
            source_object=shared_default,
        )
        self.assertEqual(result, shared_default)
        self.assertTrue(reference.selected)

    def test_get_or_create_selected_ignores_non_initial_shared_preference(self):
        shared = UserListViewPreference.objects.create(
            user=self.normal_user,
            content_type=self.content_type,
            name="Optional shared view",
        )
        shared.shared_with_users.add(self.admin_user)

        result = self.manager.get_or_create_selected(
            UserListViewPreference,
            self.scope,
        )

        self.assertEqual(result.user, self.admin_user)
        self.assertTrue(result.selected)
        self.assertFalse(
            UserListViewPreference.objects.filter(
                user=self.admin_user,
                source_object=shared,
            ).exists()
        )

    def test_saving_selected_preference_deselects_siblings_in_same_scope(self):
        first = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="First",
            selected=True,
        )
        second = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Second",
            selected=False,
        )

        second.selected = True
        second.save(update_fields=["selected"])

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.selected)
        self.assertTrue(second.selected)

    def test_saving_selected_preference_preserves_other_scopes(self):
        other_content_type = ContentType.objects.get_for_model(
            UserListViewPreference
        )
        first_scope = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=self.content_type,
            name="Customer view",
            selected=True,
        )
        second_scope = UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=other_content_type,
            name="Preference view",
            selected=True,
        )

        first_scope.refresh_from_db()
        second_scope.refresh_from_db()
        self.assertTrue(first_scope.selected)
        self.assertTrue(second_scope.selected)

    def test_database_rejects_multiple_selected_unscoped_preferences(self):
        Sidebar.objects.create(
            user=self.admin_user,
            name="Primary",
            selected=True,
        )
        secondary = Sidebar.objects.create(
            user=self.admin_user,
            name="Secondary",
            selected=False,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Sidebar.objects.filter(pk=secondary.pk).update(selected=True)
