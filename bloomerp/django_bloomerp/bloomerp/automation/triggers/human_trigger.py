

from bloomerp.automation.triggers.base import BaseTrigger
from django import forms
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

class HumanTriggerForm:
    data = forms.JSONField(
        widget=CodeEditorWidget(
            language="json"
        )
    )


class HumanTrigger(BaseTrigger):
    config_form = HumanTriggerForm
    