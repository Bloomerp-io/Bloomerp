

from bloomerp.automation.base_executor import NodeExecutionError
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
    
    def execute(self, trigger_data):
        data = self.config.get("data")
        if not data:
            raise NodeExecutionError
        return data