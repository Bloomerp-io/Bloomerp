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

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
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
                        lambda preference: preference.options["kanban"]
                        == {
                            "group_by_field": "age",
                            "page_size": 50,
                            "sort_field": "first_name",
                            "sort_direction": "desc",
                        }
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
