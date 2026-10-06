"""Recipient suggestion contracts and permission boundaries."""

from django.http import HttpResponse
from bloomerp.filters.definition import FilterCondition
from bloomerp.models import User
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import BloomerpComponentTestCase, ExpectedResult, RequestScenario


class TestSearchEmailAddressComponent(BloomerpComponentTestCase):
    """Verify optional search never exposes inaccessible email fields."""

    view_name = "components_search_email_address"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Exercise search, deduplication, authentication, and field filtering."""
        self.normal_user.email = "suggestion@example.com"
        self.normal_user.save(update_fields=["email"])
        self.admin_user.email = "suggestion@example.com"
        self.admin_user.save(update_fields=["email"])
        return [
            RequestScenario(name="Login required", expected=ExpectedResult(status_code=302)),
            RequestScenario(name="Blank query", user=self.admin_user,
                            expected=ExpectedResult(response_validators=self.empty)),
            RequestScenario(name="Short query", user=self.admin_user, query_params={"q": "s"},
                            expected=ExpectedResult(response_validators=self.empty)),
            RequestScenario(name="Deduplicated matches", user=self.admin_user,
                            query_params={"q": "suggestion"},
                            expected=ExpectedResult(response_validators=self.match)),
            RequestScenario(name="No access", user=self.normal_user, query_params={"q": "suggestion"},
                            expected=ExpectedResult(response_validators=self.empty)),
            RequestScenario(name="Hidden email field", user=self.normal_user,
                            query_params={"q": "suggestion"}, prepare=self.grant_name_only,
                            expected=ExpectedResult(response_validators=self.empty)),
            RequestScenario(name="Excluded rows", user=self.normal_user,
                            query_params={"q": "suggestion"}, prepare=self.grant_excluded_rows,
                            expected=ExpectedResult(response_validators=self.empty)),
            RequestScenario(name="Readable email field", user=self.normal_user,
                            query_params={"q": "suggestion"}, prepare=self.grant_email,
                            expected=ExpectedResult(response_validators=self.match)),
            RequestScenario(name="POST rejected", user=self.admin_user, method="POST",
                            expected=ExpectedResult(status_code=405)),
        ]

    def empty(self, response: HttpResponse) -> bool:
        """Require no suggestions for inaccessible or incomplete searches."""
        return response.json() == {"suggestions": []}

    def match(self, response: HttpResponse) -> bool:
        """Require exactly one suggestion despite duplicate addresses."""
        return [item["email"] for item in response.json()["suggestions"]] == ["suggestion@example.com"]

    def grant_name_only(self, scenario: RequestScenario) -> None:
        """Grant searchable rows while withholding their email field."""
        self.grant_field("first_name")

    def grant_email(self, scenario: RequestScenario) -> None:
        """Grant searchable rows and readable email addresses."""
        self.grant_field("email")

    def grant_field(self, field: str) -> None:
        """Assign a view policy with one explicitly readable field."""
        policy = PolicyManager.create_policy(
            model_or_content_type=User, global_permissions=["view"],
            field_permissions={field: ["view"]},
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)

    def grant_excluded_rows(self, scenario: RequestScenario) -> None:
        """Grant email visibility only for rows outside the matching results."""
        policy = PolicyManager.create_policy(
            model_or_content_type=User, global_permissions=["view"],
            field_permissions={"email": ["view"]},
            row_permissions=[RowPolicyRuleContent(
                permissions=["view"],
                conditions=[FilterCondition(field_path="email", lookup_id="equals", value="excluded@example.com")],
            )],
        )
        policy.users.add(self.normal_user)
