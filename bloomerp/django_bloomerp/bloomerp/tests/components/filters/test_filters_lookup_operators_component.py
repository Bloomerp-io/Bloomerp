from django.db import models

from bloomerp.models import ApplicationField
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestFiltersLookupOperatorsComponent(BloomerpComponentTestCase):
    """Tests lookup choices rendered for filterable fields."""

    create_foreign_models = True
    view_name = "components_filters_lookup_operators"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.EventModel = create_test_models(
            app_label="bloomerp",
            model_defs={"LookupEvent": {"starts_on": models.DateField()}},
            use_bloomerp_base=True,
        )["LookupEvent"]

    def get_test_scenarios(self) -> list[RequestScenario]:
        foreign_field = ApplicationField.get_by_field(self.CustomerModel, "country")
        date_field = ApplicationField.get_by_field(self.EventModel, "starts_on")
        return [
            RequestScenario(
                name="render foreign-key operators",
                user=self.admin_user,
                view_kwargs={
                    "content_type_id": foreign_field.content_type_id,
                    "application_field_id": foreign_field.id,
                },
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('value="is_null"'),
                        self.contains_text('value="not_equals"'),
                    ]
                ),
            ),
            RequestScenario(
                name="render date operators",
                user=self.admin_user,
                view_kwargs={
                    "content_type_id": date_field.content_type_id,
                    "application_field_id": date_field.id,
                },
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text(f'value="{lookup}"')
                        for lookup in (
                            "today",
                            "this_week",
                            "last_month",
                            "this_quarter",
                            "this_year",
                            "year",
                            "month",
                            "day",
                            "week",
                        )
                    ]
                ),
            ),
        ]
