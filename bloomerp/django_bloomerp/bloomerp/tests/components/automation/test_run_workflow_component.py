from unittest.mock import patch

from bloomerp.models.automation import Workflow, WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRunStatus
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestRunWorkflowComponent(BloomerpComponentTestCase):
    """Tests the modal and builder response modes of the run endpoint."""

    view_name = "components_automation_run_workflow"

    def get_test_scenarios(self):
        return []

    def setUp(self) -> None:
        super().setUp()
        self.workflow = Workflow.objects.create(name="Builder run")
        WorkflowNode.objects.create(
            workflow=self.workflow,
            type="TRIGGER",
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {}},
        )
        self.workflow_without_trigger = Workflow.objects.create(name="No trigger")
        self.client_request_id = "29a47fcf-5046-4bd0-ad52-a62c676be029"

    def get_test_scenarios(self) -> list[RequestScenario]:
        workflow_kwargs = {"workflow_id": self.workflow.id}
        json_headers = {"Accept": "application/json"}
        return [
            RequestScenario(
                name="render run form",
                user=self.admin_user,
                view_kwargs=workflow_kwargs,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Run workflow"),
                        self.contains_text('name="data"'),
                    ],
                ),
            ),
            RequestScenario(
                name="run synchronous workflow from builder",
                method="POST",
                user=self.admin_user,
                view_kwargs=workflow_kwargs,
                data={"data": "{}", "client_request_id": self.client_request_id},
                headers=json_headers,
                expected=ExpectedResult(
                    response_validators=[
                        self.json_key_equals("status", WorkflowRunStatus.SUCCEEDED),
                        self.json_key_equals("run_asynchronously", False),
                        self._workflow_run_has_status(WorkflowRunStatus.SUCCEEDED),
                    ],
                ),
            ),
            RequestScenario(
                name="queue workflow configured for asynchronous execution",
                method="POST",
                user=self.admin_user,
                view_kwargs=workflow_kwargs,
                data={"data": "{}", "client_request_id": self.client_request_id},
                headers=json_headers,
                prepare=self._prepare_async_workflow,
                expected=ExpectedResult(
                    status_code=202,
                    response_validators=[
                        self.json_key_equals("status", WorkflowRunStatus.QUEUED),
                        self.json_key_equals("run_asynchronously", True),
                        self._workflow_run_has_status(WorkflowRunStatus.QUEUED),
                        self._celery_dispatch_uses_response_run_id(),
                    ],
                ),
            ),
            RequestScenario(
                name="reject invalid client request id",
                method="POST",
                user=self.admin_user,
                view_kwargs=workflow_kwargs,
                data={"data": "{}", "client_request_id": "not-a-uuid"},
                headers=json_headers,
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=self.key_in_json("errors"),
                ),
            ),
            RequestScenario(
                name="reject workflow without trigger",
                method="POST",
                user=self.admin_user,
                view_kwargs={"workflow_id": self.workflow_without_trigger.id},
                data={"data": "{}"},
                headers=json_headers,
                expected=ExpectedResult(
                    status_code=400,
                    response_validators=self.json_exact(
                        {
                            "errors": {
                                "workflow": ["Workflow does not have a trigger."]
                            }
                        }
                    ),
                ),
            ),
            RequestScenario(
                name="reject user without workflow access",
                method="POST",
                user=self.normal_user,
                view_kwargs=workflow_kwargs,
                data={"data": "{}"},
                headers=json_headers,
                expected=ExpectedResult(status_code=403),
            ),
        ]

    def _prepare_async_workflow(self, _setup: RequestScenario) -> None:
        self.workflow.run_asynchronously = True
        self.workflow.save(update_fields=["run_asynchronously"])
        delay_patch = patch("bloomerp.automation.run.run_workflow_async.delay")
        self.async_delay_mock = delay_patch.start()
        self.addCleanup(delay_patch.stop)

    def _workflow_run_has_status(self, expected_status: WorkflowRunStatus):
        def validator(response) -> bool:
            run_id = response.json().get("workflow_run_id")
            return self.workflow.runs.filter(
                pk=run_id,
                status=expected_status,
            ).exists()

        return self._named_validator(
            f"workflow_run_has_status({expected_status!r})",
            validator,
        )

    def _celery_dispatch_uses_response_run_id(self):
        def validator(response) -> bool:
            return (
                self.async_delay_mock.call_count == 1
                and self.async_delay_mock.call_args.args[3]
                == response.json().get("workflow_run_id")
            )

        return self._named_validator(
            "celery_dispatch_uses_response_run_id",
            validator,
        )
