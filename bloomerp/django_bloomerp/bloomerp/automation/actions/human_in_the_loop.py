from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.results import PauseResult
from django import forms

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from bloomerp.communication.inbox_sources import publish_event
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class HumanInTheLoopForm(BaseWorkflowNodeForm):
    """Form for configuring the Human in the Loop action."""
    message = forms.CharField(
        label="Message to User",
        required=True,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="The message that will be displayed to the user when the workflow is paused."
    )
    approver_users = forms.MultipleChoiceField(
        label="Approver Users",
        widget=ForeignFieldWidget(
            attrs={
                "is_m2m": True,
                "class" : "input w-full"
            }
        ),
        help_text="Users that can approve this workflow",
        required=False,
    )
    approver_groups = forms.MultipleChoiceField(
        widget=ForeignFieldWidget(
            model=Group,
            attrs={
                "is_m2m": True,
                "class" : "input w-full"
            }
        ),
        help_text="Users belonging to groups that can approve this workflow",
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["approver_users"].widget.model = get_user_model()
    

class HumanInTheLoopExecutor(BaseExecutor):
    """An action that pauses the workflow and waits for a human to provide input."""
    config_form = HumanInTheLoopForm

    def execute(self, trigger_data: dict) -> PauseResult:
        return PauseResult(output=trigger_data)
    
    @classmethod
    def get_output_schema(
        cls,
        config=None,
        input_schema=None,
        port_id="default",
    ):
        return input_schema
    
    
