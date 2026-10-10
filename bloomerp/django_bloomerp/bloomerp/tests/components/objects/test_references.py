"""Declarative request contracts for readable reference target search."""

from bloomerp.models import FileNode, Label
from bloomerp.models.project_management.todo import Todo
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestReferenceSearch(BloomerpComponentTestCase):
    """Verify real route discovery and readable target results."""

    view_name = "components_objects_references"
    auto_create_customers = False

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover authentication, search, invalid kinds, and denied object visibility."""
        Label.objects.create(name="Urgent", created_by=self.admin_user)
        Todo.objects.create(
            title="SharedPickerSearch", content="Configured content match"
        )
        FileNode.objects.create(
            name="ExcludedLibraryFile", content="excluded.txt", kind="FILE"
        )
        self.admin_user.is_staff = True
        self.admin_user.first_name = "Picker"
        self.admin_user.last_name = "Administrator"
        self.admin_user.save(update_fields=["is_staff", "first_name", "last_name"])
        return [
            RequestScenario(
                name="Requires login", expected=ExpectedResult(status_code=302)
            ),
            RequestScenario(
                name="Shared label catalogue",
                user=self.normal_user,
                query_params={"kind": "label", "q": "urge"},
                expected=ExpectedResult(
                    response_validators=self.contains_text("Urgent")
                ),
            ),
            RequestScenario(
                name="Denied object rows",
                user=self.normal_user,
                query_params={"kind": "object"},
                expected=ExpectedResult(
                    response_validators=self.json_key_equals("items", [])
                ),
            ),
            RequestScenario(
                name="Shared model-prefixed object search includes presentation metadata",
                user=self.admin_user,
                query_params={"kind": "object", "q": "//todo/SharedPickerSearch"},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("SharedPickerSearch"),
                        self.contains_text('"model_label"'),
                        self.contains_text('"icon"'),
                        self.contains_text('"url"'),
                    ]
                ),
            ),
            RequestScenario(
                name="Shared user search matches words across name fields",
                user=self.admin_user,
                query_params={"kind": "user", "q": "Picker Administrator"},
                expected=ExpectedResult(
                    response_validators=self.contains_text("Picker Administrator")
                ),
            ),
            RequestScenario(
                name="Empty user picker offers authorized staff",
                user=self.admin_user,
                query_params={"kind": "user"},
                expected=ExpectedResult(
                    response_validators=self.contains_text("Picker Administrator")
                ),
            ),
            RequestScenario(
                name="Denied query cannot reveal object matches",
                user=self.normal_user,
                query_params={"kind": "object", "q": "SharedPickerSearch"},
                expected=ExpectedResult(
                    response_validators=self.json_key_equals("items", [])
                ),
            ),
            RequestScenario(
                name="Object picker excludes users",
                user=self.admin_user,
                query_params={"kind": "object", "q": "Picker Administrator"},
                expected=ExpectedResult(
                    response_validators=self.json_key_equals("items", [])
                ),
            ),
            RequestScenario(
                name="Object picker excludes file models even with explicit prefixes",
                user=self.admin_user,
                query_params={"kind": "object", "q": "//filenode/ExcludedLibraryFile"},
                expected=ExpectedResult(
                    response_validators=self.json_key_equals("items", [])
                ),
            ),
            RequestScenario(
                name="Dedicated file picker still includes files",
                user=self.admin_user,
                query_params={"kind": "file", "q": "ExcludedLibraryFile"},
                expected=ExpectedResult(
                    response_validators=self.contains_text("ExcludedLibraryFile")
                ),
            ),
            RequestScenario(
                name="Invalid kind rejected",
                user=self.admin_user,
                query_params={"kind": "invalid"},
                expected=ExpectedResult(status_code=400),
            ),
        ]
