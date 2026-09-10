from functools import partial

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from bloomerp.automation.run import load_step_output, resume_workflow
from bloomerp.channels.workflows.events import send_workflow_run_event
from bloomerp.models import WorkflowRun
from bloomerp.models.automation.workflow_run import WorkflowRunStatus
from bloomerp.models.automation.workflow_run_step import (
    WorkflowRunStep,
    WorkflowRunStepStatus,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.requests import (
    ExtraButton,
    render_blank_form,
    render_page_refresh_with_message,
)
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

class ApproveWorkflowContinuationForm(forms.Form):
    data = forms.JSONField(
        widget=CodeEditorWidget(
            language="json"
        )
    )


@router.register(
    path="components/automation/approve_workflow_continuation/<str:workflow_run_id>",
    url_name="components_automation_approve_workflow_continuation"
)
@login_required
def approve_workflow_continuation(request: HttpRequest, workflow_run_id: str) -> HttpResponse:
    """Component to approve a workflow continuation

    Args:
        request (HttpRequest): the request object
        workflow_run_id (str): the workflow run id

    Returns:
        HttpResponse: summary for the continuation
    """
    workflow_run = get_object_or_404(WorkflowRun, id=workflow_run_id)
    
    paused_step : WorkflowRunStep = workflow_run.steps.filter(
        status=WorkflowRunStepStatus.PAUSED
    ).first()
    
    if not paused_step:
        return HttpResponse(
            status=404,
            content="Workflow run doesn't have a paused step"
        )
    
    parameters: dict = paused_step.node.parameters or {}
    approver_groups = parameters.get("approver_groups", [])
    approver_users = parameters.get("approver_users", [])
    
    user_in_users = get_user_model().objects.filter(
        id__in=approver_users
    ).contains(
        request.user
    )
    user_in_groups = request.user.groups.filter(
        id__in=approver_groups
    ).exists()
    has_access_to_workflow = UserPolicyManager(request.user).has_access_to_object(workflow_run.workflow, BloomerpPermission.CHANGE)
    
    
    if not (user_in_users or user_in_groups or has_access_to_workflow):
        return HttpResponse(status=403, content="No permission to approve this workflow")
    
    output_step_data = load_step_output(paused_step)
    
    
    form = ApproveWorkflowContinuationForm(
        data=request.POST if request.method=="POST" else None,
        initial={
            "data" : output_step_data
        }
    )
    if request.POST and form.is_valid():
        
        if "cancel" in request.POST and request.POST.get("cancel") == "true":
            with transaction.atomic():
                paused_step.status = WorkflowRunStepStatus.CANCELLED
                paused_step.save(update_fields=["status", "datetime_updated"])

                workflow_run.status = WorkflowRunStatus.CANCELLED
                workflow_run.finished_at = timezone.now()
                workflow_run.save(
                    update_fields=["status", "finished_at", "datetime_updated"]
                )
                transaction.on_commit(
                    partial(
                        send_workflow_run_event,
                        workflow_run,
                        "run.cancelled",
                    )
                )
            
            return render_page_refresh_with_message(
                request,
                message="Workflow cancelled",
                type="info"
            )
        
        resumed_workflow = resume_workflow(
            paused_step,
            output_data=form.cleaned_data.get("data") or output_step_data
        )
        
        return render_page_refresh_with_message(
            request,
            message=(
                "Workflow resumed"
                if resumed_workflow is not None
                else "Workflow resume queued"
            ),
            type="info"
        )
    
    
    return render_blank_form(
        request,
        form=form,
        url=reverse(
            "components_automation_approve_workflow_continuation",
            kwargs={
                "workflow_run_id" : workflow_run_id
            }
        ),
        text=parameters.get(
            "message",
            "You have been asked to review the output for the workflow node"
        ),
        extra_buttons=[
            ExtraButton(
                label="Cancel Workflow Run",
                type="danger",
                attrs={
                    "name" : "cancel",
                    "value" : "true",
                    "type" : "submit"
                }
            )
        ]
    )
