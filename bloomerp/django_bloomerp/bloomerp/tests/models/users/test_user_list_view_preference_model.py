from functools import partial
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connections, models
from django.db.migrations.state import ModelState, ProjectState

from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    BloomerpModelConfig,
    ModelViewSettings,
    get_model_config,
)
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file_node import FileNode
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    BloomerpModelTestCase,
    ExpectedModelException,
    ModelScenario,
)
from bloomerp.tests.models.default_filters_scenarios import default_filter_scenarios


class TestUserListViewPreferenceModel(BloomerpModelTestCase, BaseBloomerpTestCaseWithModels):
    model = UserListViewPreference

    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user(username='owner')
        self.other_user = get_user_model().objects.create_user(username='recipient')
        self.content_type = ContentType.objects.get_for_model(Todo)

    def test_view_mode_migration_round_trip(self) -> None:
        """Exercise schema and data conversion in an isolated SQLite database."""
        alias = "drawer_migration"
        connections.databases[alias] = {**connections.databases["default"], "ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        connection = connections[alias]
        connection.connect()
        state = ProjectState()
        state.add_model(ModelState("bloomerp", "UserListViewPreference", [
            ("id", models.AutoField(primary_key=True)),
            ("split_view_enabled", models.BooleanField(default=False)),
        ]))
        old_model = state.apps.get_model("bloomerp", "UserListViewPreference")
        migration = import_module("bloomerp.migrations.0093_list_view_mode").Migration("0093_list_view_mode", "bloomerp")
        try:
            with connection.schema_editor() as editor:
                editor.create_model(old_model)
            old_model.objects.using(alias).create(split_view_enabled=False)
            old_model.objects.using(alias).create(split_view_enabled=True)
            with connection.schema_editor() as editor:
                migrated = migration.apply(state.clone(), editor)
            new_model = migrated.apps.get_model("bloomerp", "UserListViewPreference")
            self.assertEqual(list(new_model.objects.using(alias).order_by("pk").values_list("view_mode", flat=True)), ["normal", "split"])
            new_model.objects.using(alias).create(view_mode="drawer")
            with connection.schema_editor() as editor:
                migration.unapply(state.clone(), editor)
            self.assertEqual(list(old_model.objects.using(alias).order_by("pk").values_list("split_view_enabled", flat=True)), [False, True, False])
        finally:
            connection.close()
            del connections[alias]
            del connections.databases[alias]

    def get_test_scenarios(self) -> list[ModelScenario[UserListViewPreference]]:
        """Cover default views and ownership rules using live application models."""
        builtin_columns = {
            "User": ("username", "first_name", "last_name", "email", "is_active", "is_staff"),
            "Policy": ("name", "row_policy", "field_policy", "datetime_updated"),
            "ApiKey": (
                "name",
                "account",
                "is_usable",
                "last_used_at",
                "expires_at",
                "revoked_at",
            ),
            "Form": (
                "name",
                "content_type",
                "requires_review",
                "requires_authentication",
                "opens_at",
                "closes_at",
            ),
            "FormSubmission": ("form", "persisted", "datetime_created"),
            "EmailAccount": (
                "name",
                "email_address",
                "provider",
                "status",
                "sync_enabled",
                "next_sync_at",
            ),
            "AIAgent": ("name", "provider", "model_identifier", "enabled"),
            "Workflow": (
                "name",
                "active",
                "run_asynchronously",
                "enable_logging",
                "datetime_updated",
            ),
            "WorkflowRun": ("workflow", "status", "started_at", "finished_at"),
            "DocumentTemplateStyling": ("name", "datetime_updated"),
            "SqlQuery": ("name", "datetime_updated"),
            "AIAgentAccess": ("name", "model", "all_staff_users", "all_authenticated_users"),
            "MCPIntegration": ("name", "enabled", "connection_mode", "authentication_type"),
            "CalendarBooking": (
                "title",
                "organizing_inbox",
                "meeting_duration_minutes",
                "timezone",
                "active",
            ),
            "CalendarBookingSubmission": ("name", "email", "calendar_booking", "submitted_at"),
            "CalendarEventParticipant": (
                "display_name",
                "email",
                "user",
                "event",
                "response_status",
                "responded_at",
            ),
        }
        return [
            *[
                ModelScenario(
                    name=f"{model_name} materializes safe summary columns and preserves customization",
                    create_operation=partial(self.get_builtin_preference, model_name),
                    create_validators=partial(self.builtin_defaults_are_materialized, columns),
                )
                for model_name, columns in builtin_columns.items()
            ],
            *default_filter_scenarios(self, lambda: {
                'user': self.owner, 'content_type': self.content_type, 'name': 'List',
            }),
            ModelScenario(
                name="Todo defaults materialize the configured board",
                description=(
                    "UC: A user opens the Todo list for the first time.\n"
                    "Expected Result: The configured Kanban board is created, selected, and grouped by status."
                ),
                create_operation=self.create_todo_defaults,
                create_validators=self.todo_defaults_are_materialized,
            ),
            ModelScenario(
                name="FileNode defaults materialize the configured browser",
                description=(
                    "UC: A user opens Files for the first time.\n"
                    "Expected Result: The File Browser preference is created without unsupported-view errors."
                ),
                create_operation=self.create_file_defaults,
                create_validators=self.file_defaults_are_materialized,
            ),
            ModelScenario(
                name="DocumentTemplate defaults materialize a concise table once",
                create_operation=self.get_document_template_preference,
                create_validators=self.document_template_defaults_are_materialized,
            ),
            ModelScenario(
                name="DocumentTemplate defaults preserve an existing customized view",
                create_operation=self.create_custom_document_template_preference,
                create_validators=self.custom_document_template_preference_is_preserved,
            ),
            ModelScenario(
                name="All configured data views are materialized",
                description=(
                    "UC: A model declares a default Kanban and secondary table view.\n"
                    "Expected Result: Both preferences are created with resolved fields, options, and filters."
                ),
                create_operation=self.create_customer_defaults,
                create_validators=self.customer_defaults_are_materialized,
            ),
            ModelScenario(
                name="Configured data views omit inaccessible fields",
                description=(
                    "UC: A normal user has no policy for configured data-view fields.\n"
                    "Expected Result: Display, grouping, sorting, and filter fields are not persisted."
                ),
                create_operation=self.create_restricted_defaults,
                create_validators=self.restricted_fields_are_omitted,
            ),
            ModelScenario(
                name="Unknown configured data-view field rolls back all defaults",
                description=(
                    "UC: A model configuration references a missing field.\n"
                    "Expected Result: Creation raises clearly and leaves no partial preference."
                ),
                create_operation=self.create_invalid_defaults,
                expected_exceptions=[
                    ExpectedModelException(
                        phase="create",
                        exception=ValueError,
                        message_regex="does_not_exist",
                    )
                ],
            ),
        ]

    def get_builtin_preference(self, model_name: str) -> UserListViewPreference:
        """Open a built-in model list through the normal preference manager."""
        content_type = ContentType.objects.get_for_model(
            apps.get_model("bloomerp", model_name)
        )
        selected = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference, {"content_type_id": content_type.pk}
        )
        self.assertIsInstance(selected, UserListViewPreference)
        return selected

    def builtin_defaults_are_materialized(
        self, columns: tuple[str, ...], selected: UserListViewPreference
    ) -> bool:
        """Resolve explicit safe columns, then preserve a user's changed list on reopen."""
        model = selected.content_type.model_class()
        view = get_model_config(model).model_view_settings.default_dataviews[0]
        expected_ids = [ApplicationField.get_by_field(model, name).pk for name in columns]
        self.assertEqual(selected.display_fields["table"], expected_ids)
        self.assertEqual(selected.name, view.name)
        self.assertEqual(selected.view_type, "table")
        self.assertTrue(selected.selected)
        self.assertEqual(selected.options["table"]["sort_field"], view.sort_field)
        self.assertEqual(selected.options["table"]["sort_direction"], view.sort_direction)
        self.assertEqual(self.get_builtin_preference(model.__name__).pk, selected.pk)
        selected.name = "My summary"
        selected.view_mode = "drawer"
        selected.display_fields = {"table": expected_ids[:1]}
        selected.options = {"table": {"page_size": 50}}
        selected.save()
        reopened = self.get_builtin_preference(model.__name__)
        self.assertEqual(reopened.pk, selected.pk)
        self.assertEqual(reopened.name, "My summary")
        self.assertEqual(reopened.view_mode, "drawer")
        self.assertEqual(reopened.display_fields, {"table": expected_ids[:1]})
        self.assertEqual(reopened.options, {"table": {"page_size": 50}})
        self.assertEqual(
            UserListViewPreference.objects.filter(
                user=self.admin_user, content_type=selected.content_type
            ).count(),
            1,
        )
        return True

    def get_document_template_preference(self) -> UserListViewPreference:
        """Open the template list through its ordinary preference lifecycle."""
        content_type = ContentType.objects.get_for_model(DocumentTemplate)
        selected = PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            {"content_type_id": content_type.pk},
        )
        self.assertIsInstance(selected, UserListViewPreference)
        return selected

    def document_template_defaults_are_materialized(
        self, selected: UserListViewPreference
    ) -> bool:
        """Check ordered summary columns, sorting, and repeated-open idempotence."""
        expected_field_ids = [
            ApplicationField.get_by_field(DocumentTemplate, name).pk
            for name in (
                "name",
                "page_size",
                "page_orientation",
                "include_page_numbers",
                "datetime_updated",
            )
        ]
        reopened = self.get_document_template_preference()
        return (
            selected.name == "Document templates"
            and selected.selected
            and selected.view_type == "table"
            and selected.view_mode == "normal"
            and selected.display_fields["table"] == expected_field_ids
            and selected.options["table"] == {
                "page_size": 25,
                "sort_field": "name",
                "sort_direction": "asc",
            }
            and not selected.default_filters.exists()
            and reopened.pk == selected.pk
            and UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=selected.content_type,
            ).count() == 1
        )

    def create_custom_document_template_preference(self) -> UserListViewPreference:
        """Represent a template-list preference customized before these defaults."""
        return UserListViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(DocumentTemplate),
            name="My templates",
            selected=True,
            view_type="table",
            view_mode="drawer",
            display_fields={"table": [
                ApplicationField.get_by_field(DocumentTemplate, "name").pk,
            ]},
            options={"table": {
                "page_size": 50,
                "sort_field": "name",
                "sort_direction": "desc",
            }},
        )

    def custom_document_template_preference_is_preserved(
        self, selected: UserListViewPreference
    ) -> bool:
        """Ensure repeated opens leave the user's existing list settings intact."""
        for _ in range(2):
            self.assertEqual(self.get_document_template_preference().pk, selected.pk)
        selected.refresh_from_db()
        return (
            selected.name == "My templates"
            and selected.selected
            and selected.view_type == "table"
            and selected.view_mode == "drawer"
            and selected.display_fields == {"table": [
                ApplicationField.get_by_field(DocumentTemplate, "name").pk,
            ]}
            and selected.options == {"table": {
                "page_size": 50,
                "sort_field": "name",
                "sort_direction": "desc",
            }}
            and UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=selected.content_type,
            ).count() == 1
        )

    def create_todo_defaults(self):
        self.scenario_content_type = ContentType.objects.get_for_model(Todo)
        return UserListViewPreference.create_default_for_user(
            self.admin_user,
            content_type_id=self.scenario_content_type.pk,
        )

    def todo_defaults_are_materialized(self, selected):
        preferences = list(
            UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=self.scenario_content_type,
            ).order_by("pk")
        )
        return (
            [preference.name for preference in preferences] == ["Board"]
            and selected == preferences[0]
            and selected.selected
            and selected.view_type == "kanban"
            and selected.options["kanban"]["group_by_field"] == "status"
        )

    def create_file_defaults(self) -> UserListViewPreference:
        """Materialize the configured file-node browser for the administrator."""
        self.scenario_content_type = ContentType.objects.get_for_model(FileNode)
        return UserListViewPreference.create_default_for_user(
            self.admin_user,
            content_type_id=self.scenario_content_type.pk,
        )

    @staticmethod
    def file_defaults_are_materialized(selected: UserListViewPreference) -> bool:
        """Verify file-node browsing defaults include virtual folder organization."""
        return (
            selected.selected
            and selected.view_type == "file_browser"
            and selected.options["file_browser"] == {"related_fields": {}, "folder_type": "virtual"}
        )

    @staticmethod
    def customer_view_settings():
        return ModelViewSettings(
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

    def create_customer_defaults(self):
        self.scenario_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        with patch.object(
            self.CustomerModel,
            "bloomerp_config",
            BloomerpModelConfig(model_view_settings=self.customer_view_settings()),
            create=True,
        ):
            return UserListViewPreference.create_default_for_user(
                self.admin_user,
                content_type_id=self.scenario_content_type.pk,
            )

    def customer_defaults_are_materialized(self, selected):
        preferences = list(
            UserListViewPreference.objects.filter(
                user=self.admin_user,
                content_type=self.scenario_content_type,
            ).order_by("pk")
        )
        first_name = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        last_name = ApplicationField.get_by_field(self.CustomerModel, "last_name")
        age = ApplicationField.get_by_field(self.CustomerModel, "age")
        return (
            [item.name for item in preferences] == ["Customer workflow", "Customer directory"]
            and selected == preferences[0]
            and preferences[0].selected
            and not preferences[1].selected
            and preferences[0].display_fields["kanban"] == [first_name.pk, age.pk]
            and preferences[0].options["kanban"] == {
                "group_by_field": "age",
                "page_size": 25,
                "sort_field": "first_name",
                "sort_direction": "asc",
            }
            and preferences[0].default_filters.get().filters[0]["conditions"][0]["value"] == "18"
            and preferences[1].display_fields["table"] == [last_name.pk, first_name.pk]
        )

    def create_restricted_defaults(self):
        self.scenario_content_type = ContentType.objects.get_for_model(self.CustomerModel)
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
        with patch.object(
            self.CustomerModel,
            "bloomerp_config",
            BloomerpModelConfig(model_view_settings=settings),
            create=True,
        ):
            return UserListViewPreference.create_default_for_user(
                self.normal_user,
                content_type_id=self.scenario_content_type.pk,
            )

    @staticmethod
    def restricted_fields_are_omitted(preference):
        return (
            preference.display_fields["kanban"] == []
            and preference.options["kanban"]["group_by_field"] is None
            and preference.options["kanban"]["sort_field"] is None
            and not preference.default_filters.exists()
        )

    def create_invalid_defaults(self):
        self.scenario_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        settings = ModelViewSettings(
            default_dataviews=[
                TableDataView(name="Valid", display_fields=["first_name"]),
                TableDataView(
                    name="Invalid", is_default=False, display_fields=["does_not_exist"]
                ),
            ]
        )
        with patch.object(
            self.CustomerModel,
            "bloomerp_config",
            BloomerpModelConfig(model_view_settings=settings),
            create=True,
        ):
            try:
                return UserListViewPreference.create_default_for_user(
                    self.admin_user,
                    content_type_id=self.scenario_content_type.pk,
                )
            except ValueError:
                if UserListViewPreference.objects.filter(
                    user=self.admin_user,
                    content_type=self.scenario_content_type,
                ).exists():
                    raise AssertionError("Invalid defaults left a partial preference")
                raise
