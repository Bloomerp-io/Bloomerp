from collections.abc import Callable
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse

from bloomerp.dataviews.definition import DataviewState
from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.models.files.file import File
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestUpdateDataviewPreferenceComponent(BloomerpComponentTestCase):
    """Exercise preference updates through the registered component endpoint."""

    view_name = "components_update_dataview_preference"
    create_foreign_models = True

    def extendedSetup(self):
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.view_kwargs = {"content_type_id": self.content_type.pk}
        self.file_content_type = ContentType.objects.get_for_model(File)
        self.host_content_type = ContentType.objects.get_for_model(self.CountryModel)
        self.host_object = self.CountryModel.objects.first()

    def _preference(
        self,
        view_kwargs: dict | None = None,
    ) -> UserListViewPreference:
        return PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference,
            view_kwargs or self.view_kwargs,
        )

    def _select_view(
        self,
        view_type: str,
        view_kwargs: dict | None = None,
    ) -> Callable[[RequestScenario], None]:
        def prepare(_scenario: RequestScenario) -> None:
            preference = self._preference(view_kwargs)
            preference.view_type = view_type
            preference.save(update_fields=["view_type"])

        return prepare

    def _preference_matches(
        self,
        validator: Callable[[UserListViewPreference], bool],
        view_kwargs: dict | None = None,
    ):
        def validate(_response: HttpResponse) -> bool:
            preference = self._preference(view_kwargs)
            preference.refresh_from_db()
            return validator(preference)

        validate.__name__ = getattr(validator, "__name__", "preference_matches")
        return validate

    def _spy_on_kanban_form_factory(self, _scenario: RequestScenario) -> None:
        self.form_factory_patcher = patch.object(
            KanbanDataView,
            "form_factory",
            wraps=KanbanDataView.form_factory,
        )
        self.form_factory = self.form_factory_patcher.start()

    def _stop_spying_on_kanban_form_factory(self, _scenario: RequestScenario) -> None:
        self.form_factory_patcher.stop()

    def _form_factory_receives_dataview_state(self, _response: HttpResponse) -> bool:
        return self.form_factory.called and all(
            isinstance(call.args[0], DataviewState)
            for call in self.form_factory.call_args_list
        )

    def _kanban_defaults_saved(self, preference: UserListViewPreference) -> bool:
        """Verify ordinary options persist alongside empty optional mappings."""
        return preference.options["kanban"] == {
            "group_by_field": "age",
            "custom_groupings": {},
            "custom_group_order": [],
            "lane_colouring": {},
            "page_size": 50,
            "sort_field": "first_name",
            "sort_direction": "desc",
        }

    def _prepare_mapping_options(self, scenario: RequestScenario) -> None:
        """Select numeric grouping and submit the reusable widget's indexed rows."""
        country = self.CountryModel.objects.get(name="Belgium")
        for age in [20, 30]:
            self.CustomerModel.objects.create(first_name="Mapping", last_name="Test", age=age, country=country)
        preference = self._preference()
        preference.view_type = "kanban"
        preference.options = {"kanban": {"group_by_field": "age"}}
        preference.save(update_fields=["view_type", "options"])
        scenario.data.update({
            "custom_groupings__rows": ["0"],
            "custom_groupings__key_0": "Young",
            "custom_groupings__value_0": ["20", "30"],
            "lane_colouring__rows": ["0"],
            "lane_colouring__key_0": "Young",
            "lane_colouring__value_0": "#123456",
        })

    def _mapping_options_saved(self, _response: HttpResponse) -> bool:
        """Check that indexed mapping rows reach persisted typed options."""
        options = self._preference().options["kanban"]
        return options["custom_groupings"] == {"Young": ["20", "30"]} and options["lane_colouring"] == {"Young": "#123456"}

    def _prepare_reordered_mappings(self, scenario: RequestScenario) -> None:
        """Submit rows in DOM order with deliberately nonsequential input identifiers."""
        self._prepare_mapping_options(scenario)
        scenario.data.update({
            "custom_groupings__rows": ["7", "2"],
            "custom_groupings__key_7": "1. Instroom",
            "custom_groupings__value_7": ["20"],
            "custom_groupings__key_2": "5. Aanbod",
            "custom_groupings__value_2": ["30"],
        })

    def _reordered_mappings_saved(self, response: HttpResponse) -> bool:
        """Verify explicit order survives saving and drives the returned mapping editor."""
        options = self._preference().options["kanban"]
        html = response.content.decode()
        return (
            options["custom_group_order"] == ["1. Instroom", "5. Aanbod"]
            and options["custom_groupings"] == {"1. Instroom": ["20"], "5. Aanbod": ["30"]}
            and html.index('value="1. Instroom"') < html.index('value="5. Aanbod"')
        )

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover preference operations and their persisted configuration."""
        return [
            RequestScenario(
                name="Persist explicit Kanban row order",
                method="POST", user=self.admin_user, view_kwargs=self.view_kwargs,
                data={"dataview_options_view_type": "kanban", "group_by_field": "age"},
                prepare=self._prepare_reordered_mappings,
                expected=ExpectedResult(response_validators=self._reordered_mappings_saved),
            ),
            RequestScenario(
                name="Persist indexed Kanban mapping widget rows",
                method="POST", user=self.admin_user, view_kwargs=self.view_kwargs,
                prepare=self._prepare_mapping_options,
                data={"dataview_options_view_type": "kanban", "group_by_field": "age", "page_size": "25", "sort_direction": "asc"},
                expected=ExpectedResult(response_validators=self._mapping_options_saved),
            ),
            RequestScenario(
                name="Reject GET requests",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                expected=ExpectedResult(status_code=405),
            ),
            RequestScenario(
                name="Change view type",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                data={"view_type": "card"},
                expected=ExpectedResult(
                    response_validators=self._preference_matches(
                        lambda preference: preference.view_type == "card"
                    )
                ),
            ),
            RequestScenario(
                name="Change to unconfigured Gantt view",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                data={"view_type": "gantt"},
                expected=ExpectedResult(
                    response_validators=[
                        self._preference_matches(
                            lambda preference: preference.view_type == "gantt"
                        ),
                        self.contains_text('name="start_field"'),
                        self.contains_text('name="end_field"'),
                    ]
                ),
            ),
            RequestScenario(
                name="Change split view",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                data={"split_view_enabled": "true"},
                expected=ExpectedResult(
                    response_validators=self._preference_matches(
                        lambda preference: preference.split_view_enabled
                    )
                ),
            ),
            RequestScenario(
                name="Persist Kanban options using field names",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                prepare=self._select_view("kanban"),
                data={
                    "dataview_options_view_type": "kanban",
                    "group_by_field": "age",
                    "page_size": "50",
                    "sort_field": "first_name",
                    "sort_direction": "desc",
                },
                expected=ExpectedResult(
                    response_validators=self._preference_matches(
                        self._kanban_defaults_saved
                    )
                ),
            ),
            RequestScenario(
                name="Provide dataview state to the Kanban form factory",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                prepare=[
                    self._select_view("kanban"),
                    self._spy_on_kanban_form_factory,
                ],
                cleanup=self._stop_spying_on_kanban_form_factory,
                data={
                    "dataview_options_view_type": "kanban",
                    "group_by_field": "age",
                    "page_size": "25",
                    "sort_field": "",
                    "sort_direction": "asc",
                },
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    response_validators=self._form_factory_receives_dataview_state
                ),
            ),
            RequestScenario(
                name="Persist file browser options in the host scope",
                method="POST",
                user=self.admin_user,
                view_kwargs={"content_type_id": self.file_content_type.pk},
                prepare=self._select_view(
                    "file_browser",
                    {"content_type_id": self.file_content_type.pk},
                ),
                data={
                    "dataview_options_view_type": "file_browser",
                    "related_fields": ["customers"],
                },
                query_params={
                    "content_type": self.host_content_type.pk,
                    "object_id": self.host_object.pk,
                },
                headers={"HX-Request": "true"},
                expected=ExpectedResult(response_validators=[
                    self._preference_matches(
                        lambda preference: preference.options["file_browser"]
                        ["related_fields"]
                        == {str(self.host_content_type.pk): ["customers"]},
                        {"content_type_id": self.file_content_type.pk},
                    ),
                    self.contains_text('value="customers" selected'),
                    self.contains_text(f"content_type={self.host_content_type.pk}"),
                    self.contains_text(f"object_id={self.host_object.pk}"),
                ]),
            ),
            RequestScenario(
                name="Persist file browser options for a non-file preference",
                method="POST",
                user=self.admin_user,
                view_kwargs={"content_type_id": self.host_content_type.pk},
                prepare=self._select_view(
                    "file_browser",
                    {"content_type_id": self.host_content_type.pk},
                ),
                data={
                    "dataview_options_view_type": "file_browser",
                    "related_fields": ["customers"],
                },
                headers={"HX-Request": "true"},
                expected=ExpectedResult(response_validators=[
                    self._preference_matches(
                        lambda preference: preference.options["file_browser"]
                        ["related_fields"]
                        == {str(self.host_content_type.pk): ["customers"]},
                        {"content_type_id": self.host_content_type.pk},
                    ),
                    self.contains_text('value="customers" selected'),
                ]),
            ),
            RequestScenario(
                name="Persist Calendar options using field names",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                prepare=self._select_view("calendar"),
                data={
                    "dataview_options_view_type": "calendar",
                    "start_field": "date_joined",
                    "end_field": "",
                    "view_mode": "month",
                    "color_grouping_field": "age",
                },
                expected=ExpectedResult(
                    response_validators=self._preference_matches(
                        lambda preference: preference.options["calendar"]
                        == {
                            "start_field": "date_joined",
                            "end_field": None,
                            "view_mode": "month",
                            "color_grouping_field": "age",
                        }
                    )
                ),
            ),
            RequestScenario(
                name="Reject an unknown option field name",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                prepare=self._select_view("kanban"),
                data={
                    "dataview_options_view_type": "kanban",
                    "group_by_field": "does_not_exist",
                    "page_size": "25",
                    "sort_field": "",
                    "sort_direction": "asc",
                },
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="Reject options for a different active view",
                method="POST",
                user=self.admin_user,
                view_kwargs=self.view_kwargs,
                prepare=self._select_view("table"),
                data={
                    "dataview_options_view_type": "kanban",
                    "group_by_field": "age",
                    "page_size": "25",
                    "sort_field": "",
                    "sort_direction": "asc",
                },
                expected=ExpectedResult(status_code=400),
            ),
        ]


class TestReorderDataviewFields(BloomerpComponentTestCase):
    """Verify field reordering persists only an authorized permutation for the current view."""

    view_name = "components_update_dataview_preference"
    create_foreign_models = True

    def extendedSetup(self) -> None:
        """Resolve model fields and independent per-view preference orders."""
        from bloomerp.models import ApplicationField

        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.view_kwargs = {"content_type_id": self.content_type.pk}
        self.first_id = ApplicationField.get_by_field(self.CustomerModel, "first_name").pk
        self.last_id = ApplicationField.get_by_field(self.CustomerModel, "last_name").pk
        self.age_id = ApplicationField.get_by_field(self.CustomerModel, "age").pk
        self.hidden_id = ApplicationField.get_by_field(self.CustomerModel, "country").pk
        self.foreign_id = ApplicationField.get_by_field(self.CountryModel, "name").pk
        self.initial_order = [self.first_id, self.last_id, self.age_id]
        self.new_order = [self.age_id, self.first_id, self.last_id]

    def _selected_preference(self) -> UserListViewPreference:
        """Load the administrator's selected preference for the tested model."""
        return PreferenceManager(self.admin_user).get_or_create_selected(
            UserListViewPreference, self.view_kwargs
        )

    def _prepare_order(self, _scenario: RequestScenario) -> None:
        """Reset visibility and give another view a different saved order."""
        preference = self._selected_preference()
        preference.view_type = "kanban"
        preference.set_visible_field_ids("kanban", self.initial_order.copy())
        preference.set_visible_field_ids("table", [self.last_id, self.first_id])
        preference.save(update_fields=["view_type", "display_fields"])

    def _order_saved(self, response: HttpResponse) -> bool:
        """Check persistence, rendered chip ordering and the canonical card field order."""
        from bloomerp.services.user_services import get_data_view_fields

        preference = self._selected_preference()
        fields = get_data_view_fields(preference, user=self.admin_user)
        html = response.content.decode()
        positions = [html.index(f'data-field-id="{field_id}"') for field_id in self.new_order]
        return (
            preference.get_visible_field_ids("kanban") == self.new_order
            and preference.get_visible_field_ids("table") == [self.last_id, self.first_id]
            and [field.pk for field in fields.visible_fields] == self.new_order
            and [field.pk for field, visible in fields.ordered_fields if visible] == self.new_order
            and positions == sorted(positions)
            and html.index(f'data-field-id="{self.hidden_id}"') > positions[-1]
        )

    def _order_unchanged(self, _response: HttpResponse) -> bool:
        """Confirm rejected submissions do not alter visible fields or their order."""
        return self._selected_preference().get_visible_field_ids("kanban") == self.initial_order

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover valid ordering and reject malformed, incomplete or inaccessible permutations."""
        scenarios = [
            RequestScenario(
                name="Save current view field order and render matching chip order",
                method="POST", user=self.admin_user, view_kwargs=self.view_kwargs,
                prepare=self._prepare_order,
                data={"reorder_view_type": "kanban", "field_order": self.new_order},
                expected=ExpectedResult(response_validators=self._order_saved),
            )
        ]
        for name, view_type, order, status_code in [
            ("Reject duplicate fields", "kanban", [self.first_id, self.first_id, self.age_id], 400),
            ("Reject missing visible field", "kanban", [self.first_id, self.last_id], 400),
            ("Reject hidden field becoming visible", "kanban", [self.first_id, self.last_id, self.hidden_id], 400),
            ("Reject another model's field", "kanban", [self.first_id, self.last_id, self.foreign_id], 403),
            ("Reject malformed field", "kanban", [self.first_id, "bad", self.age_id], 400),
            ("Reject changing another view", "table", self.new_order, 400),
        ]:
            scenarios.append(RequestScenario(
                name=name, method="POST", user=self.admin_user, view_kwargs=self.view_kwargs,
                prepare=self._prepare_order,
                data={"reorder_view_type": view_type, "field_order": order},
                expected=ExpectedResult(status_code=status_code, response_validators=self._order_unchanged),
            ))
        return scenarios
