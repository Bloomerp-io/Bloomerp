import html
import re
from typing import Any

from bloomerp.communication.emails.email_providers import EmailProviderDefinition
from bloomerp.communication.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget

from ..base_executor import BaseExecutor
from bloomerp.automation.schema import (
    WorkflowInputRequirement,
    WorkflowIOSchema,
    WorkflowValueField,
    remap_schema_field_paths,
)
from bloomerp.automation.values import TEMPLATE_PATTERN, get_path_value, stringify_value
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
    body = forms.CharField(label="Email Body", widget=BloomerpTextEditorWidget)
    body_format = forms.CharField(widget=forms.HiddenInput, initial="html")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Show legacy plain text safely when an old node opens in the editor."""
        initial = kwargs.get("initial")
        if isinstance(initial, dict) and initial.get("body_format") != "html":
            legacy_body = initial.get("body")
            if isinstance(legacy_body, str) and legacy_body:
                converted_body = html.escape(legacy_body).replace("\n", "<br>")
                kwargs["initial"] = {
                    **initial,
                    "body": f"<p>{converted_body}</p>",
                    "body_format": "html",
                }
        super().__init__(*args, **kwargs)


def resolve_email_html_body(template: str, input_data: dict) -> str:
    """Escape workflow values inserted into author-created email HTML."""

    def replace_reference(match: re.Match[str]) -> str:
        """Resolve one workflow reference as safe HTML text."""
        value = get_path_value({"input": input_data}, match.group(1))
        return html.escape(stringify_value(value), quote=True)

    return TEMPLATE_PATTERN.sub(replace_reference, template)


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
        """Include the upstream fields alongside the email send result fields."""
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
        """Send editor HTML safely while preserving legacy plain-text bodies."""
        params = self.resolve_config(input_data)
        recipient = stringify_value(params.get("recipient"))
        subject = stringify_value(params.get("subject"))
        is_html_body = self.config.get("body_format") == "html"
        if is_html_body:
            configured_body = self.config.get("body", "")
            body = (
                resolve_email_html_body(configured_body, input_data)
                if isinstance(configured_body, str)
                else html.escape(stringify_value(params.get("body")), quote=True)
            )
        else:
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
            body_text=None if is_html_body else body,
            body_html=body if is_html_body else None,
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
