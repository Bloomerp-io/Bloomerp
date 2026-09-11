from django.db import models

from bloomerp.models import ApplicationField
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestValueInputComponent(BloomerpComponentTestCase):
    """Tests the value editor selected for each filter lookup."""

    create_foreign_models = True
    view_name = "components_filters_value_input"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.EventModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "FilterEvent": {
                    "starts_at": models.DateTimeField(),
                    "starts_on": models.DateField(),
                    "is_active": models.BooleanField(default=False),
                }
            },
            use_bloomerp_base=True,
        )["FilterEvent"]

    def get_test_scenarios(self) -> list[RequestScenario]:
        first_name = ApplicationField.get_by_field(self.CustomerModel, "first_name")
        country = ApplicationField.get_by_field(self.CustomerModel, "country")
        created_by = ApplicationField.get_by_field(self.CustomerModel, "created_by")
        starts_at = ApplicationField.get_by_field(self.EventModel, "starts_at")
        starts_on = ApplicationField.get_by_field(self.EventModel, "starts_on")

        return [
            self._scenario(
                "render text input",
                first_name,
                "equals",
                '<input',
                'class="input w-full"',
            ),
            self._scenario(
                "ignore stale choice metadata",
                first_name,
                "equals",
                '<input',
                'class="input w-full"',
                excluded=("Full Time",),
                prepare=self._add_stale_choice_metadata(first_name),
            ),
            self._scenario(
                "render null boolean select",
                first_name,
                "is_null",
                '<select',
                'class="select w-full"',
                '<option value="true">True</option>',
                '<option value="false">False</option>',
            ),
            self._scenario(
                "render datetime-local input",
                starts_at,
                "equals",
                '<input',
                'type="datetime-local"',
                'class="input w-full"',
            ),
            self._scenario(
                "render relative-date hidden input",
                starts_on,
                "this_week",
                'type="hidden"',
                'name="starts_on"',
                'value="true"',
            ),
            self._scenario(
                "render year input",
                starts_on,
                "year",
                'type="number"',
                'min="1"',
            ),
            self._scenario(
                "render bounded month input",
                starts_on,
                "month",
                'type="number"',
                'min="1"',
                'max="12"',
            ),
            self._scenario(
                "render bounded day input",
                starts_on,
                "day",
                'type="number"',
                'min="1"',
                'max="31"',
            ),
            self._scenario(
                "render bounded week input",
                starts_on,
                "week",
                'type="number"',
                'min="1"',
                'max="53"',
            ),
            self._scenario(
                "render day-of-week select",
                starts_on,
                "day_of_week",
                '<select',
                '<option value="0">Monday</option>',
                '<option value="6">Sunday</option>',
            ),
            self._scenario(
                "render current-user advanced lookup",
                created_by,
                "equals_user",
                'name="country__user"',
                'value="$user"',
                query_params={"field_path": "country__user"},
            ),
            self._scenario(
                "preserve advanced field path prefix",
                country,
                "foreign_advanced",
                'data-base-field="employee_on_project__employee"',
                'data-path-prefix="employee_on_project__employee"',
                query_params={
                    "field_path": "employee_on_project__employee",
                },
            ),
            self._scenario(
                "preserve original base field id",
                country,
                "foreign_advanced",
                'data-base-field-id="123"',
                query_params={
                    "field_path": "parent_department__parent_department",
                    "base_application_field_id": "123",
                },
            ),
            self._scenario(
                "reject invalid foreign current value",
                country,
                "foreign_equals",
                query_params={"current_value": "dasdasdsa"},
                status_code=400,
            ),
        ]

    def _scenario(
        self,
        name,
        application_field,
        lookup_value,
        *included,
        excluded=(),
        query_params=None,
        prepare=None,
        status_code=200,
    ) -> RequestScenario:
        validators = [self.contains_text(value) for value in included]
        validators.extend(self.does_not_contain_text(value) for value in excluded)
        return RequestScenario(
            name=name,
            user=self.admin_user,
            view_kwargs={
                "content_type_id": application_field.content_type_id,
                "application_field_id": application_field.id,
            },
            query_params={
                "lookup_value": lookup_value,
                **(query_params or {}),
            },
            prepare=prepare,
            expected=ExpectedResult(
                status_code=status_code,
                response_validators=validators,
            ),
        )

    @staticmethod
    def _add_stale_choice_metadata(application_field):
        def prepare(_setup: RequestScenario) -> None:
            application_field.meta = {
                "choices": [
                    ["full_time", "Full Time"],
                    ["part_time", "Part Time"],
                ]
            }
            application_field.save(update_fields=["meta"])

        return prepare
