"""Shared real-policy fixtures for the two workflow-node read components."""

from django.http import HttpResponse

from bloomerp.models.automation import Workflow, WorkflowNode
from bloomerp.permissions.definition import RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.tests.base import ExpectedResult, RequestScenario


class WorkflowNodeReadScenarios:
    """Exercise parent access without mocking node lookup or permission evaluation."""

    marker = "SEC12-HARMLESS-PRIVATE-HEADER"

    def prepare_node_read_fixtures(self) -> None:
        """Create private and permitted workflows with harmless API configuration."""
        self.private_workflow = Workflow.objects.create(name="SEC12 private")
        self.visible_workflow = Workflow.objects.create(name="SEC12 visible")
        self.private_node = WorkflowNode.objects.create(
            workflow=self.private_workflow,
            type="ACTION",
            sub_type="CALL_API",
            parameters={
                "endpoint": "https://example.invalid/fixture",
                "method": "GET",
                "headers": {"Authorization": self.marker},
                "payload": {},
            },
        )
        self.visible_node = WorkflowNode.objects.create(
            workflow=self.visible_workflow,
            type="ACTION",
            sub_type="CALL_API",
            parameters=self.private_node.parameters,
        )

    def grant_visible_workflow(self, scenario: RequestScenario) -> None:
        """Grant view access to exactly one workflow, as the builder requires."""
        policy = PolicyManager.create_policy(
            model_or_content_type=Workflow,
            field_permissions={"name": ["view"]},
            row_permissions=[RowPolicyRuleContent(
                permissions=["view"],
                connector="AND",
                conditions=[RowPolicyRuleCondition(
                    field="name", operator="equals", value=self.visible_workflow.name,
                )],
            )],
        )
        policy.assign_user(self.normal_user)
        self.read_policy = policy

    def grant_global_only(self, scenario: RequestScenario) -> None:
        """Keep the global view grant but remove access to workflow rows."""
        self.grant_visible_workflow(scenario)
        self.read_policy.row_policy.rules.all().delete()

    def grant_row_only(self, scenario: RequestScenario) -> None:
        """Keep a matching row grant but remove the required global permission."""
        self.grant_visible_workflow(scenario)
        self.read_policy.global_permissions.clear()

    def validate_editable_parameters(self, response: HttpResponse) -> bool:
        """Verify authorized form/JSON reads preserve stored values without writes."""
        form = response.context["form"]
        initial = form.initial.get("parameters", form.initial)
        self.visible_node.refresh_from_db()
        return (
            initial["headers"]["Authorization"] == self.marker
            and self.visible_node.parameters["headers"]["Authorization"] == self.marker
        )

    def node_read_scenarios(self) -> list[RequestScenario]:
        """Cover no-grant, global/row boundaries, and both authorized editing modes."""
        scenarios = [
            RequestScenario(
                name="node read requires login",
                query_params={"node_id": self.private_node.pk},
                expected=ExpectedResult(status_code=302),
            ),
            RequestScenario(
                name="node read requires an id",
                user=self.admin_user,
                expected=ExpectedResult(status_code=400),
            ),
            RequestScenario(
                name="unknown node is not found",
                user=self.admin_user,
                query_params={"node_id": 2147483647},
                expected=ExpectedResult(status_code=404),
            ),
        ]
        for mode in ("form", "json"):
            query = {"node_id": self.private_node.pk, "edit_mode": mode, "refresh_form": "1"}
            for name, prepare in (
                ("no workflow grant", None),
                ("grant to another workflow", self.grant_visible_workflow),
            ):
                scenarios.append(RequestScenario(
                    name=f"deny {mode} read with {name}",
                    user=self.normal_user,
                    query_params=query.copy(),
                    prepare=prepare,
                    expected=ExpectedResult(
                        status_code=404,
                        response_validators=self.does_not_contain_text(self.marker),
                    ),
                ))
            visible_query = {**query, "node_id": self.visible_node.pk}
            scenarios.append(RequestScenario(
                name=f"allow row-authorized {mode} editing",
                user=self.normal_user,
                query_params=visible_query.copy(),
                prepare=self.grant_visible_workflow,
                expected=ExpectedResult(response_validators=self.validate_editable_parameters),
            ))
            for name, prepare in (
                ("global permission without row access", self.grant_global_only),
                ("row access without global permission", self.grant_row_only),
            ):
                scenarios.append(RequestScenario(
                    name=f"deny {mode} read with {name}",
                    user=self.normal_user,
                    query_params=visible_query.copy(),
                    prepare=prepare,
                    expected=ExpectedResult(status_code=404),
                ))
        scenarios.append(RequestScenario(
            name="deny schema-only read for an unrelated user",
            user=self.normal_user,
            query_params={"node_id": self.private_node.pk},
            prepare=self.grant_visible_workflow,
            expected=ExpectedResult(status_code=404),
        ))
        return scenarios
