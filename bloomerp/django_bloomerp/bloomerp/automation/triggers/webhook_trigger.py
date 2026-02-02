from bloomerp.automation.triggers.base import BaseTrigger
from django import forms
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

class WebhookForm(forms.Form):
    pass


class WebhookTrigger(BaseTrigger):
    config_form = WebhookForm
    