from bloomerp.communication.emails.email_providers import EmailProviderDefinition
from bloomerp.communication.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

from ..base_executor import BaseExecutor
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    remap_schema_field_paths,
)
from bloomerp.automation.values import stringify_value
from django.forms import Form
from django import forms

class SendEmailForm(Form):
    from_account = forms.CharField(
        label="From Account",
        widget=ForeignFieldWidget(
            model=EmailAccount,
            attrs={
                "class" : "input w-full"
            }
        )
    )
    recipient = forms.CharField(
        label="Recipient Email",
        help_text="Use a literal email or a value reference like {{ input.instance.email }}.",
    )
    subject = forms.CharField(label="Email Subject", max_length=255)
    body = forms.CharField(label="Email Body", widget=forms.Textarea)


class SendEmailExecutor(BaseExecutor):
    config_form = SendEmailForm
    input_requirement = WorkflowInputRequirement(
        value_type="any",
        label="Any input",
        description="Use references from upstream data in recipient, subject, or body.",
    )
    output_schema = WorkflowIOSchema(
        value_type="object",
        label="Email result",
        description="Details about the email send attempt.",
        fields=[
            WorkflowValueField("input.email.recipient", "Email Recipient", "string"),
            WorkflowValueField("input.email.subject", "Email Subject", "string"),
            WorkflowValueField("input.email.body", "Email Body", "string"),
            WorkflowValueField("input.email.status", "Email Status", "string"),
        ],
    )

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
        port_id: str = "default",
    ) -> WorkflowIOSchema:
        upstream_fields = (
            remap_schema_field_paths(input_schema.fields, {})
            if input_schema and input_schema.value_type != "none"
            else []
        )
        if not upstream_fields:
            return cls.output_schema

        return WorkflowIOSchema(
            value_type=input_schema.value_type if input_schema else "object",
            label=f"{input_schema.label or 'Input'} with email result",
            description="Upstream data plus details about the email send attempt.",
            fields=[
                *upstream_fields,
                *cls.output_schema.fields,
            ],
        )
    
    def execute(self, input_data: dict) -> dict:
        params = self.resolve_config(input_data)
        recipient = stringify_value(params.get("recipient"))
        subject = stringify_value(params.get("subject"))
        body = stringify_value(params.get("body"))
        from_email = params.get("from_account")
        
        # Get the email account
        email_account = EmailAccount.objects.get(id=from_email)
        provider: EmailProviderDefinition | None = EMAIL_PROVIDER_REGISTRY.get(
            email_account.provider
        )
        if provider is None:
            raise ValueError(f"Unsupported email provider: {email_account.provider}")
        adapter = provider.adapter_class(
            email_account
        )
        
        # Send the email using the adapter
        adapter.send_email(
            to=[recipient],
            subject=subject,
            body_text=body,
            body_html=None,
        )
        
        
        output_data = input_data if isinstance(input_data, dict) else {"input": input_data}
        return {
            **output_data,
            "email": {
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "status": "sent",
            },
        }
