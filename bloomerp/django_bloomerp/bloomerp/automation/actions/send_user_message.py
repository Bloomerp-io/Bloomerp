from bloomerp.utils.realtime import send_user_message
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, WorkflowValueField, WorkflowValueType
from django.forms import Form
from django import forms
from django.contrib.auth import get_user_model


# TODO: Choices should be defined in a central place
class SendUserMessageForm(Form):
    user_id = forms.CharField(
        widget=ForeignFieldWidget(
            model=get_user_model(),
            attrs={"class" : "input w-full"}
        ),
        help_text="Use a literal user id or a value reference like {{ input.id }}.",
    )
    message = forms.CharField(widget=forms.Textarea)
    message_type = forms.ChoiceField(
        choices=[
            ("success", "Success"),
            ("info", "Info"),
            ("warning", "Warning"),
            ("error", "Error"),
        ],
    )

class SendUserMessage(BaseExecutor):
    config_form = SendUserMessageForm
    input_requirement = WorkflowInputRequirement(
        value_type="any",
        label="Any input",
        description="Use upstream references to pick the recipient user or message text.",
    )
    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.NONE,
        label="No output",
    )
    
    def execute(self, input_data: dict) -> dict:
        params = self.resolve_config(input_data)
        user_id = params.get("user_id")
        
        send_user_message(
            user_id,
            payload={
                "type": "toast", 
                "message": str(params.get("message")), 
                "level": params.get("message_type", "success")
            }
        )
        
        
        

