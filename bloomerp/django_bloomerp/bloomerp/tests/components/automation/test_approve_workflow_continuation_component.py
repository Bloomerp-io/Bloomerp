from unittest.mock import Mock, patch

from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.models import User
from bloomerp.models.automation import Workflow, WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRun, WorkflowRunStatus
from bloomerp.models.automation.workflow_run_step import (
    WorkflowRunStep,
    WorkflowRunStepStatus,
)
from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestSetup,
)


class TestApproveWorkflowContinuationComponent(BloomerpComponentTestCase):
    """Tests the workflow-continuation approval component."""

    view_name = "components_automation_approve_workflow_continuation"

    def setUp(self) -> None:
        super().setUp()
        self.user = User.objects.create_user(
            username="workflow-approver",
            password="password",
        )
        self.workflow = Workflow.objects.create(name="Approval workflow")
        self.approval_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            type="ACTION",
            sub_type="HUMAN_IN_THE_LOOP",
            parameters={},
        )
        self.workflow_run = WorkflowRun.objects.create(
            workflow=self.workflow,
            status=WorkflowRunStatus.PAUSED,
        )
        WorkflowRunStep.objects.create(
            workflow_run=self.workflow_run,
            node=self.approval_node,
            sequence=1,
            action_id="HUMAN_IN_THE_LOOP",
            status=WorkflowRunStepStatus.PAUSED,
        )

    def get_request_setups(self) -> list[RequestSetup]:
        view_kwargs = {"workflow_run_id": self.workflow_run.id}
        return [
            RequestSetup(
                name="reject user without approval access",
                user=self.user,
                view_kwargs=view_kwargs,
                prepare=self._prepare_component,
                expected=ExpectedResult(status_code=403),
            ),
            RequestSetup(
                name="allow explicitly configured approver",
                user=self.user,
                view_kwargs=view_kwargs,
                prepare=self._prepare_explicit_approver,
            ),
            RequestSetup(
                name="allow configured approver group member",
                user=self.user,
                view_kwargs=view_kwargs,
                prepare=self._prepare_group_approver,
            ),
            RequestSetup(
                name="allow user with workflow change access",
                user=self.user,
                view_kwargs=view_kwargs,
                prepare=self._prepare_superuser,
            ),
        ]

    def _prepare_component(self, _setup: RequestSetup) -> None:
        output_patch = patch(
            "bloomerp.components.automation.approve_workflow_continuation.load_step_output",
            return_value={},
        )
        form_patch = patch(
            "bloomerp.components.automation.approve_workflow_continuation.render_blank_form",
            return_value=HttpResponse("Approval form"),
        )
        output_patch.start()
        form_patch.start()
        self.addCleanup(output_patch.stop)
        self.addCleanup(form_patch.stop)

    def _set_approvers(self, *, users=None, groups=None) -> None:
        self.approval_node.parameters = {
            "approver_users": users or [],
            "approver_groups": groups or [],
        }
        self.approval_node.save(update_fields=["parameters"])

    def _prepare_explicit_approver(self, setup: RequestSetup) -> None:
        self._prepare_component(setup)
        self._set_approvers(users=[self.user.id])

    def _prepare_group_approver(self, setup: RequestSetup) -> None:
        self._prepare_component(setup)
        group = Group.objects.create(name="Workflow approvers")
        self.user.groups.add(group)
        self._set_approvers(groups=[group.id])

    def _prepare_superuser(self, setup: RequestSetup) -> None:
        self._prepare_component(setup)
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

    def test_async_approval_reports_that_resume_was_queued(self):
        """
        Use case: An approver continues an asynchronous workflow.
        Expected result: The response says the resume was queued instead of completed.
        """
        # 1. Configure the workflow and user for asynchronous approval.
        self.workflow.run_asynchronously = True
        self.workflow.save(update_fields=["run_asynchronously"])
        self._set_approvers(users=[self.user.id])
        self.client.force_login(self.user)
        approval_form = Mock()
        approval_form.is_valid.return_value = True
        approval_form.cleaned_data = {"data": {}}

        # 2. Submit approval while isolating the asynchronous dispatcher and response.
        with (
            patch(
                "bloomerp.components.automation.approve_workflow_continuation.load_step_output",
                return_value={},
            ),
            patch(
                "bloomerp.components.automation.approve_workflow_continuation.ApproveWorkflowContinuationForm",
                return_value=approval_form,
            ),
            patch(
                "bloomerp.components.automation.approve_workflow_continuation.resume_workflow",
                return_value=None,
            ),
            patch(
                "bloomerp.components.automation.approve_workflow_continuation.render_page_refresh_with_message",
                return_value=HttpResponse(),
            ) as render_message,
        ):
            response = self.client.post(
                reverse(
                    self.view_name,
                    kwargs={"workflow_run_id": self.workflow_run.id},
                ),
                {"data": "{}"},
            )

        # 3. Verify the UI reports queueing rather than premature completion.
        self.assertEqual(response.status_code, 200)
        render_message.assert_called_once()
        self.assertEqual(
            render_message.call_args.kwargs["message"],
            "Workflow resume queued",
        )
