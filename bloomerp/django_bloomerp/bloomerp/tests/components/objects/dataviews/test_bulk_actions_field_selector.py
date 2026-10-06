from django.contrib.contenttypes.models import ContentType

from bloomerp.models import ApplicationField
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestBulkActionsFieldSelector(BloomerpComponentTestCase):
    """Keep bulk form values separate from the dataview's record filters."""

    auto_create_customers = False
    view_name = "components_bulk_actions_field_selector"

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise field changes and filtered selection with HTMX form inputs."""
        self.create_customer("Selected", "Customer", 30)
        self.create_customer("Unselected", "Customer", 31)
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        application_field = ApplicationField.get_for_model(self.CustomerModel).get(
            field="first_name",
        )
        view_kwargs = {"content_type_id": content_type.pk}
        query_params = {
            "selection": "filtered",
            "action": "bulk_change",
            "csrfmiddlewaretoken": "test-token",
            "application_field_id": str(application_field.pk),
            "first_name": "Selected",
        }
        scenarios = [
            RequestScenario(
                name=f"switch field with {description} bulk value",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                query_params={**query_params, "value": value},
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    response_validators=self.contains_text('name="value"'),
                ),
            )
            for description, value in (
                ("blank", ""),
                ("populated", "Replacement"),
                ("multiple", ["Replacement", "Another"]),
            )
        ]
        scenarios.append(
            RequestScenario(
                name="retain record filters while ignoring the bulk value",
                view_name="components_bulk_actions",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                query_params={**query_params, "value": "Replacement"},
                headers={"HX-Request": "true"},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Delete 1 object(s)"),
                        self.does_not_contain_text("Delete 2 object(s)"),
                    ],
                ),
            ),
        )
        return scenarios
