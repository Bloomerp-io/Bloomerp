from .base import BaseExecutor
from django.forms import Form
from django import forms

class SendEmailForm(Form):
    recipient = forms.EmailField(label="Recipient Email")
    subject = forms.CharField(label="Email Subject", max_length=255)
    body = forms.CharField(label="Email Body", widget=forms.Textarea)


class SendEmailExecutor(BaseExecutor):
    form = SendEmailForm
    
    def execute(self, input_data:str) -> dict:
        return {"status": "email_sent"}
    
    