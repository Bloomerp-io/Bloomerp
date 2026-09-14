from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from unittest.mock import patch

from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import BloomerpModelConfig, ModelViewSettings
from bloomerp.models.project_management.todo import Todo
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels, BloomerpModelTestCase, ExpectedModelException, ModelScenario
from bloomerp.tests.models.default_filters_scenarios import default_filter_scenarios


class TestUserListViewPreferenceModel(BloomerpModelTestCase, BaseBloomerpTestCaseWithModels):
    model = UserListViewPreference

    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user(username='owner')
        self.other_user = get_user_model().objects.create_user(username='recipient')
        self.content_type = ContentType.objects.get_for_model(Todo)

    def get_test_scenarios(self) -> list[ModelScenario[UserListViewPreference]]:
        return [
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
        status = ApplicationField.get_by_field(Todo, "status")
        return (
            [preference.name for preference in preferences] == ["Board"]
            and selected == preferences[0]
            and selected.selected
            and selected.view_type == "kanban"
            and selected.options["kanban"]["group_by_field_id"] == status.pk
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
                "group_by_field_id": age.pk,
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
            and preference.options["kanban"]["group_by_field_id"] is None
            and preference.options["kanban"]["sort_field"] is None
            and not preference.default_filters.exists()
        )

    def create_invalid_defaults(self):
        self.scenario_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        settings = ModelViewSettings(
            default_dataviews=[
                TableDataView(name="Valid", display_fields=["first_name"]),
                TableDataView(name="Invalid", is_default=False, display_fields=["does_not_exist"]),
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
