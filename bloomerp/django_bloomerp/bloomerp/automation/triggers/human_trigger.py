


from bloomerp.automation.base_executor import NodeExecutionError
from bloomerp.automation.triggers.base import BaseTrigger
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, WorkflowValueType, WorkflowValueField, WorkflowValueType
from django import forms
from bloomerp.automation.utils import json_to_type_and_fields
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

class HumanTriggerForm(forms.Form):
    data = forms.JSONField(
        widget=CodeEditorWidget(
            language="json"
        )
    )


class HumanTrigger(BaseTrigger):
    config_form = HumanTriggerForm
    label = "Human Trigger"
    input_description = "Manual test triggers start workflows and do not receive upstream input."
    
    def execute(self, trigger_data):
        data = self.config.get("data")
        if not data:
            raise NodeExecutionError
        if isinstance(data, dict) and isinstance(trigger_data, dict):
            merged_data = data.copy()
            merged_data.update(trigger_data)
            return merged_data
        if trigger_data in ({}, None):
            return data
        return trigger_data

    @classmethod
    def get_input_requirement(cls, config = None):
        return WorkflowInputRequirement(
            value_type="none",
            label="No input",
            description=cls.input_description,
        )

    @classmethod
    def get_output_schema(cls, config=None, input_schema=None):
        data = (config or {}).get("parameters", {}).get("data")
        if data is None:
            return WorkflowIOSchema(
                value_type=WorkflowValueType.NONE,
                label=cls.label,
            )

        value_type, fields = json_to_type_and_fields(data)
        if value_type == WorkflowValueType.ANY:
            fields = [
                WorkflowValueField(
                    path="input",
                    label="Input",
                    value_type=WorkflowValueType.ANY,
                )
            ]
        
        return WorkflowIOSchema(
            value_type=value_type,
            label=cls.label,
            fields=fields
        )
    
    
    
