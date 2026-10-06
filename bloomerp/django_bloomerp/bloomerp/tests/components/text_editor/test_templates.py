"""Shared template picker permissions and search contracts."""

from django.contrib.contenttypes.models import ContentType
from bloomerp.models import DocumentTemplate, User
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import BloomerpComponentTestCase, ExpectedResult, RequestScenario


class TestEditorTemplates(BloomerpComponentTestCase):
    """Exercise searchable copies without content-type restrictions."""

    view_name = "components_text_editor_templates"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover authentication, name filtering, arbitrary roots, and field visibility."""
        generic = DocumentTemplate.objects.create(name="Generic", template="<p>Generic copy</p>")
        rooted = DocumentTemplate.objects.create(name="Rooted", template="<p>{{ user.email }}</p>")
        rooted.content_types.add(ContentType.objects.get_for_model(User))
        return [
            RequestScenario(name="Requires login", expected=ExpectedResult(status_code=302)),
            RequestScenario(name="All content types", user=self.admin_user, expected=ExpectedResult(
                response_validators=[self.contains_text("Generic copy"), self.contains_text("user.email")],
            )),
            RequestScenario(name="Search by name", user=self.admin_user, query_params={"q": "root"},
                            expected=ExpectedResult(response_validators=[
                                self.contains_text("Rooted"), self.does_not_contain_text("Generic copy"),
                            ])),
            RequestScenario(name="No model access", user=self.normal_user,
                            expected=ExpectedResult(response_validators=self.json_key_equals("templates", []))),
            RequestScenario(name="Hidden body", user=self.normal_user, prepare=self.grant_name,
                            expected=ExpectedResult(response_validators=self.json_key_equals("templates", []))),
            RequestScenario(name="Readable templates", user=self.normal_user, prepare=self.grant_all,
                            expected=ExpectedResult(response_validators=self.contains_text("Generic copy"))),
        ]

    def grant_name(self, scenario: RequestScenario) -> None:
        """Allow rows without disclosing template content."""
        self.grant_fields({"name": ["view"]})

    def grant_all(self, scenario: RequestScenario) -> None:
        """Allow reading all fields of template rows."""
        self.grant_fields({"__all__": ["view"]})

    def grant_fields(self, fields: dict[str, list[str]]) -> None:
        """Assign a real policy for the current field visibility scenario."""
        policy = PolicyManager.create_policy(
            model_or_content_type=DocumentTemplate, global_permissions=["view"],
            field_permissions=fields,
            row_permissions=[RowPolicyRuleContent(permissions=["view"], conditions=[])],
        )
        policy.users.add(self.normal_user)
