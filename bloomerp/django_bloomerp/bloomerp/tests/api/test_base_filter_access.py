"""Verify configured model filters at the generated API boundary."""

from collections.abc import Callable
from unittest.mock import patch

from django.http import HttpResponse

from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.definition import ApiAccessSettings, ApiSettings
from bloomerp.models.project_management.todo import Todo, TodoPriority, TodoStatus
from bloomerp.permissions.definition import AccessRule, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    ExpectedResult,
    RequestScenario,
    RequestTestCaseMixin,
)


class TestBaseFilterApiAccess(RequestTestCaseMixin, BaseBloomerpTestCaseWithModels):
    """Exercise generated routes using shared declarative request scenarios."""

    # Generated DRF routes are outside Bloomerp's view route registry.
    view_name = "todos-list"
    auto_create_customers = False

    def setUp(self) -> None:
        """Create rows that distinguish model filtering from caller row grants."""
        super().setUp()
        self.included = Todo.objects.create(
            title="Included", status=TodoStatus.BACKLOG, priority=TodoPriority.MEDIUM
        )
        self.excluded = Todo.objects.create(
            title="Excluded", status=TodoStatus.SCOPED, priority=TodoPriority.MEDIUM
        )
        self.denied_by_policy = Todo.objects.create(
            title="Policy denied", status=TodoStatus.BACKLOG, priority=TodoPriority.HIGH
        )
        read_rule = AccessRule(
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"],
                    conditions=[
                        FilterCondition(
                            field_path="priority", lookup_id="equals", value="medium"
                        )
                    ],
                )
            ],
            field_permissions={"id": ["view"], "title": ["view"]},
        )
        config = Todo.bloomerp_config.model_copy(
            update={
                "base_filter": Filter(
                    connector="AND",
                    conditions=[
                        FilterCondition(
                            field_path="status", lookup_id="equals", value="backlog"
                        )
                    ],
                ),
                "api_settings": ApiSettings(
                    access=ApiAccessSettings(
                        anonymous=[read_rule],
                        inherit_anonymous_for_authenticated=False,
                    )
                ),
            }
        )
        self.enterContext(patch.object(Todo, "bloomerp_config", config))
        policy = PolicyManager.create_policy(
            Todo,
            field_permissions={
                "id": ["view", "change"],
                "title": ["view", "change"],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view", "change", "delete"],
                    conditions=[
                        FilterCondition(
                            field_path="priority", lookup_id="equals", value="medium"
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Cover filtered reads and writes for superusers, policies and public rules."""
        scenarios: list[RequestScenario] = []
        for label, user, visible in (
            ("superuser", self.admin_user, [self.included, self.denied_by_policy]),
            ("stored policy", self.normal_user, [self.included]),
            ("anonymous access rule", None, [self.included]),
        ):
            scenarios.extend(
                [
                    RequestScenario(
                        name=f"{label}: list intersects access with the model filter",
                        user=user,
                        expected=ExpectedResult(
                            response_validators=self.list_has_todos(visible)
                        ),
                    ),
                    RequestScenario(
                        name=f"{label}: excluded row cannot be retrieved",
                        view_name="todos-detail",
                        user=user,
                        view_kwargs={"pk": self.excluded.pk},
                        expected=ExpectedResult(status_code=404),
                    ),
                ]
            )
        for label, user in (
            ("superuser", self.admin_user),
            ("stored policy", self.normal_user),
        ):
            scenarios.extend(
                [
                    RequestScenario(
                        name=f"{label}: excluded row cannot be updated",
                        view_name="todos-detail",
                        method="PATCH",
                        user=user,
                        view_kwargs={"pk": self.excluded.pk},
                        content_type="application/json",
                        data={"title": "Forbidden edit"},
                        expected=ExpectedResult(
                            status_code=404,
                            response_validators=self.excluded_todo_is_unchanged,
                        ),
                    ),
                    RequestScenario(
                        name=f"{label}: excluded row cannot be deleted",
                        view_name="todos-detail",
                        method="DELETE",
                        user=user,
                        view_kwargs={"pk": self.excluded.pk},
                        expected=ExpectedResult(
                            status_code=404,
                            response_validators=self.excluded_todo_is_unchanged,
                        ),
                    ),
                    RequestScenario(
                        name=f"{label}: included row remains writable",
                        view_name="todos-detail",
                        method="PATCH",
                        user=user,
                        view_kwargs={"pk": self.included.pk},
                        content_type="application/json",
                        data={"title": "Updated"},
                        expected=ExpectedResult(
                            response_validators=self.included_todo_was_updated
                        ),
                    ),
                ]
            )
        return scenarios

    def list_has_todos(self, todos: list[Todo]) -> Callable[[HttpResponse], bool]:
        """Build a validator for the exact visible row identities in a list response."""
        expected_ids = {str(todo.pk) for todo in todos}

        def validate_todos(response: HttpResponse) -> bool:
            """Compare returned row identities without depending on ordering or fields."""
            return {item["id"] for item in response.json()} == expected_ids

        return validate_todos

    def excluded_todo_is_unchanged(self, response: HttpResponse) -> bool:
        """Ensure a denied mutation preserved the excluded row and its title."""
        return Todo.objects.filter(pk=self.excluded.pk, title="Excluded").exists()

    def included_todo_was_updated(self, response: HttpResponse) -> bool:
        """Confirm allowed API writes persist and return the changed title."""
        return (
            response.json()["title"] == "Updated"
            and Todo.objects.filter(pk=self.included.pk, title="Updated").exists()
        )
