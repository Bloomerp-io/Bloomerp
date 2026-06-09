from django import forms

from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, WorkflowValueField
from bloomerp.automation.triggers.base import BaseTrigger
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from bloomerp.widgets.code_editor_widget import CodeEditorWidget


class ScheduleTriggerConfigForm(BaseWorkflowNodeForm):
    schedule = forms.CharField(
        label="Cron Schedule",
        help_text="Enter a cron expression to define the schedule for this trigger. For example, '0 9 * * *' to run every day at 9 AM.",
    )
    timezone = forms.CharField(
        required=False,
        label="Timezone",
        help_text="Optional timezone for this schedule. Leave blank to use the project timezone.",
    )
    data = forms.JSONField(
        required=False,
        widget=CodeEditorWidget(language="json"),
        initial=dict,
    )


class ScheduleTrigger(BaseTrigger):
    config_form = ScheduleTriggerConfigForm
    input_requirement = WorkflowInputRequirement(
        value_type="none",
        label="No input",
        description="Scheduled triggers start workflows and do not receive upstream input.",
    )
    output_schema = WorkflowIOSchema(
        value_type="object",
        label="Scheduled trigger",
        description="The schedule event that started the workflow.",
        fields=[
            WorkflowValueField(
                path="event",
                label="Event",
                value_type="string",
            ),
            WorkflowValueField(
                path="scheduled_at",
                label="Scheduled At",
                value_type="datetime",
            ),
            WorkflowValueField(
                path="data",
                label="Trigger Data",
                value_type="object",
            ),
        ],
    )

    def execute(self, trigger_data):
        config_data = self.config.get("data") or {}
        runtime_data = trigger_data.get("data", {}) if isinstance(trigger_data, dict) else {}

        return {
            "event": "schedule",
            "scheduled_at": trigger_data.get("scheduled_at") if isinstance(trigger_data, dict) else None,
            "data": {
                **config_data,
                **runtime_data,
            },
        }
