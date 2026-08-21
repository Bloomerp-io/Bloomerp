from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    BloomerpModelConfig,
    KanbanDataView,
    ModelViewSettings,
    TableDataView,
)
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.tests.base import BaseBloomerpModelTestCase


class UserListViewPreferenceDefaultTests(BaseBloomerpModelTestCase):
    def setUp(self):
        super().setUp()
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)

    def test_todo_model_defaults_materialize_as_a_kanban_and_table(self):
        """
        Use case: A user opens the Todo list for the first time.
        Expected result: Todo's concrete Kanban and table setups are both created.
        """
        # 1. Materialize the defaults declared directly on the Todo model.
        content_type = ContentType.objects.get_for_model(Todo)
        selected = UserListViewPreference.create_default_for_user(
            self.admin_user,
            content_type_id=content_type.pk,
        )

        # 2. Verify the workflow is selected and the table remains available.
        preferences = list(
            UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=content_type,
            ).order_by("pk")
        )
        self.assertEqual(
            [preference.name for preference in preferences],
            ["Todo workflow", "All todos"],
        )
        self.assertEqual(selected, preferences[0])
        self.assertEqual(selected.view_type, "kanban")

        # 3. Verify the status grouping field resolved to its ApplicationField ID.
        status_field = ApplicationField.get_by_field(Todo, "status")
        self.assertEqual(
            selected.options["kanban"]["group_by_field_id"],
            status_field.pk,
        )

    def test_create_default_for_user_materializes_all_configured_dataviews(self):
        """
        Use case: A model provides a selected Kanban view and a secondary table view.
        Expected result: Both preferences are created with resolved field IDs and options.
        """
        # 1. Configure two declarative data views using model field names.
        settings = ModelViewSettings(
            default_dataviews=[
                KanbanDataView(
                    name="Customer workflow",
                    display_fields=["first_name", "age"],
                    group_by_field="age",
                    sort_field="first_name",
                    default_filters={"age__gte": "18"},
                ),
                TableDataView(
                    name="Customer directory",
                    is_default=False,
                    display_fields=["last_name", "first_name"],
                    sort_field="last_name",
                ),
            ]
        )

        # 2. Create the defaults for a superuser with access to every field.
        with patch.object(
            self.CustomerModel,
            "bloomerp_config",
            BloomerpModelConfig(model_view_settings=settings),
            create=True,
        ):
            selected = UserListViewPreference.create_default_for_user(
                self.admin_user,
                content_type_id=self.content_type.pk,
            )

        # 3. Verify all setups and the configured selection were materialized.
        preferences = list(
            UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=self.content_type,
            ).order_by("pk")
        )
        self.assertEqual(
            [item.name for item in preferences],
            ["Customer workflow", "Customer directory"],
        )
        self.assertEqual(selected, preferences[0])
        self.assertTrue(preferences[0].selected)
        self.assertFalse(preferences[1].selected)

        # 4. Verify field names became the existing persistence representation.
        first_name = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        last_name = ApplicationField.get_by_field(self.CustomerModel, "last_name")
        age = ApplicationField.get_by_field(self.CustomerModel, "age")
        self.assertEqual(
            preferences[0].display_fields["kanban"],
            [first_name.pk, age.pk],
        )
        self.assertEqual(
            preferences[0].options["kanban"],
            {
                "group_by_field_id": age.pk,
                "page_size": 25,
                "sort_field": "first_name",
                "sort_direction": "asc",
            },
        )
        self.assertEqual(preferences[0].default_filters, {"age__gte": "18"})
        self.assertEqual(
            preferences[1].display_fields["table"],
            [last_name.pk, first_name.pk],
        )

    def test_configured_dataviews_do_not_persist_inaccessible_fields(self):
        """
        Use case: A normal user has no field policy for configured data-view fields.
        Expected result: Display, option, and filter fields are omitted from the preference.
        """
        # 1. Configure fields across display, grouping, sorting, and filtering.
        settings = ModelViewSettings(
            default_dataviews=[
                KanbanDataView(
                    name="Restricted workflow",
                    display_fields=["first_name", "age"],
                    group_by_field="age",
                    sort_field="first_name",
                    default_filters={"age__gte": "18"},
                )
            ]
        )

        # 2. Materialize the setup for a user without an applicable field policy.
        with patch.object(
            self.CustomerModel,
            "bloomerp_config",
            BloomerpModelConfig(model_view_settings=settings),
            create=True,
        ):
            preference = UserListViewPreference.create_default_for_user(
                self.normal_user,
                content_type_id=self.content_type.pk,
            )

        # 3. Verify no configured field bypassed the user's permissions.
        self.assertEqual(preference.display_fields["kanban"], [])
        self.assertIsNone(preference.options["kanban"]["group_by_field_id"])
        self.assertIsNone(preference.options["kanban"]["sort_field"])
        self.assertEqual(preference.default_filters, {})

    def test_unknown_configured_dataview_field_rolls_back_all_defaults(self):
        """
        Use case: A developer references a field that does not exist on the model.
        Expected result: Creation fails clearly without leaving partial preferences.
        """
        # 1. Configure one valid setup followed by an invalid field reference.
        settings = ModelViewSettings(
            default_dataviews=[
                TableDataView(name="Valid", display_fields=["first_name"]),
                TableDataView(
                    name="Invalid",
                    is_default=False,
                    display_fields=["does_not_exist"],
                ),
            ]
        )

        # 2. Attempt to materialize the configured defaults.
        with patch.object(
            self.CustomerModel,
            "bloomerp_config",
            BloomerpModelConfig(model_view_settings=settings),
            create=True,
        ), self.assertRaisesRegex(ValueError, "does_not_exist"):
            UserListViewPreference.create_default_for_user(
                self.admin_user,
                content_type_id=self.content_type.pk,
            )

        # 3. Verify the atomic operation did not retain the first preference.
        self.assertFalse(
            UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=self.content_type,
            ).exists()
        )
