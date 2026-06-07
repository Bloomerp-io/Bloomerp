from pytest import param

from bloomerp.utils.realtime import send_user_message

from ..base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, WorkflowValueField
from bloomerp.automation.values import stringify_value
from django.forms import Form
from django import forms

class SendUserMessageForm(Form):
    user_id = forms.CharField(
        help_text="Use a literal user id or a value reference like {{ input.id }}.",
    )
    message = forms.CharField(widget=forms.Textarea)
    

class SendUserMessage(BaseExecutor):
    config_form = SendUserMessageForm
    input_requirement = WorkflowInputRequirement(
        kind="any",
        label="Any input",
        description="Use upstream references to pick the recipient user or message text.",
    )
    output_schema = WorkflowIOSchema(
        kind="object",
        label="Message result",
        fields=[
            WorkflowValueField("input.message.user_id", "Message User ID", "number"),
            WorkflowValueField("input.message.status", "Message Status", "string"),
        ],
    )
    
    def execute(self, input_data: dict) -> dict:
        params = self.resolve_config(input_data)
        
        user_id = params.get("user_id")
        send_user_message(
            user_id,
            payload={
                "type": "toast", 
                "message": params.get("message"), 
                "level": "success"
            }
        )
        
        return {
            
        }


def send_email(recipient: str, subject: str, body: str) -> None:
    print(f"Email sent\nTo: {recipient}\nSubject: {subject}\nBody: {body}")
