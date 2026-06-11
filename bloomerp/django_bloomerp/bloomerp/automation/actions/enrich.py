

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowValueType
from django import forms

from bloomerp.automation.utils import json_to_type_and_fields
from bloomerp.widgets.code_editor_widget import CodeEditorWidget


class EnrichForm(forms.Form):
    data = forms.JSONField(
        required=True,
        label="Enrichment Data",
        widget=CodeEditorWidget(
            language="json",
        )
    )
    
    def clean(self):
        cleaned_data = super().clean()
        data = cleaned_data.get("data")
        if isinstance(data, list):
            raise forms.ValidationError("Enrichment data must be a dictionary, not a list.")
        return cleaned_data


class EnrichExecutor(BaseExecutor):
    config_form = EnrichForm
    
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.OBJECT,
        label="Object to Enrich",
        description="The object that will be enriched with additional data. The output of this action will contain all the original fields of this object, plus any additional fields specified in the executor's configuration.",
    )
    
    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        _, fields = json_to_type_and_fields((config or {}).get("parameters", {}).get("data") or {})
        input_schema.fields.extend(fields)
        return input_schema
    
    
    def execute(self, trigger_data):
        if isinstance(trigger_data, list):
            pass
        
        if not isinstance(trigger_data, dict):
            raise ValueError("EnrichExecutor only accepts dict input data.")
        
        data = self.resolve_config(trigger_data).get("data") or {}
        
        if not isinstance(data, dict):
            raise ValueError("Enrichment data must be a dictionary.")
        
        enriched_data = trigger_data.copy()
        enriched_data.update(data)
        
        return enriched_data
