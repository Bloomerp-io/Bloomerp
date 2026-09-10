from uuid import UUID

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.automation.run import run_workflow as _run_workflow
from bloomerp.models import Workflow
from bloomerp.models.automation.workflow_run import WorkflowRunStatus
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_page_refresh_with_message
from bloomerp.widgets.code_editor_widget import CodeEditorWidget


class RunWorkflowForm(forms.Form):
    data = forms.JSONField(
        label="Trigger data for this workflow",
        required=False,
        widget=CodeEditorWidget(language="json"),
    )


@router.register(
    path="components/automation/run_workflow/<str:workflow_id>",
    url_name="components_automation_run_workflow",
)
@login_required
def run_workflow(request: HttpRequest, workflow_id: str) -> HttpResponse:
    """Endpoint to run a specific workflow

    Args:
        request (HttpRequest)
        workflow_id (str)

    Returns:
        HttpResponse: for post request, a message containing the result, for get requests.
    """
    workflow = get_object_or_404(Workflow, id=workflow_id)

    if not UserPolicyManager(request.user).has_access_to_object(
        workflow,
        BloomerpPermission.CHANGE,
    ):
        return HttpResponse(status=403, content="No permission to run this workflow")

    wants_json = request.headers.get("Accept") == "application/json"
    trigger = workflow.get_trigger()
    sub_type = trigger.sub_type if trigger else None
    initial_data = (trigger.parameters or {}) if trigger else {}

    form = RunWorkflowForm(
        data=request.POST if request.method == "POST" else None,
        initial=initial_data if sub_type == "HUMAN_TRIGGER" else None,
    )

    if request.method == "POST" and form.is_valid():
        start_node_id = request.POST.get("start_node_id")
        start_node = (
            get_object_or_404(workflow.nodes, pk=start_node_id)
            if start_node_id
            else None
        )
        if start_node is None and trigger is None:
            if wants_json:
                return JsonResponse(
                    {"errors": {"workflow": ["Workflow does not have a trigger."]}},
                    status=400,
                )
            return render_page_refresh_with_message(
                request,
                message="Workflow does not have a trigger",
                type="error",
            )

        client_request_id = request.POST.get("client_request_id")
        if client_request_id:
            try:
                client_request_id = str(UUID(client_request_id))
            except ValueError:
                if wants_json:
                    return JsonResponse(
                        {"errors": {"client_request_id": ["Invalid request ID."]}},
                        status=400,
                    )
                client_request_id = None

        result = _run_workflow(
            workflow,
            form.cleaned_data.get("data", {}),
            start_node=start_node,
            client_request_id=client_request_id,
        )
        if result is None:
            if wants_json:
                return JsonResponse(
                    {"errors": {"workflow": ["Workflow is not active."]}},
                    status=409,
                )
            message = "Workflow is not active"
        elif result.status == WorkflowRunStatus.QUEUED:
            message = "Workflow starting run"
        else:
            message = f"Workflow ran with status {result.get_status_display()}"

        if wants_json and result is not None:
            return JsonResponse(
                {
                    "workflow_run_id": result.id,
                    "status": result.status,
                    "run_asynchronously": workflow.run_asynchronously,
                },
                status=202 if result.status == WorkflowRunStatus.QUEUED else 200,
            )

        return render_page_refresh_with_message(
            request,
            message=message,
            type="info",
        )

    if request.method == "POST" and wants_json:
        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)

    return render_blank_form(
        request,
        form,
        reverse(
            "components_automation_run_workflow",
            kwargs={"workflow_id": workflow.id},
        ),
        submit_label="Run workflow",
        button_attrs={"bloomerp-close-modal": "bloomerp-general-use-modal"},
        text="Run this workflow by giving the trigger data.",
    )
