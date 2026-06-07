

from typing import Any

from bloomerp.automation.base_executor import NodeExecutionError
from bloomerp.automation.triggers.base import BaseTrigger
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, WorkflowValueField
from django import forms
from bloomerp.widgets.code_editor_widget import CodeEditorWidget

class HumanTriggerForm(forms.Form):
    data = forms.JSONField(
        widget=CodeEditorWidget(
            language="json"
        )
    )


def _value_type_for_json(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _extract_fields(obj: Any, path: str = "") -> tuple[str, list[WorkflowValueField]]:
    if isinstance(obj, list):
        if len(obj) == 0:
            return "list", []

        list_item = obj[0]
        if not isinstance(list_item, (dict, list)):
            return "list", []

        child_path = f"{path}.0" if path else "0"
        _, fields = _extract_fields(list_item, child_path)
        return "list", fields

    if not isinstance(obj, dict):
        return _value_type_for_json(obj), []

    fields: list[WorkflowValueField] = []
    for key, value in obj.items():
        field_path = key if not path else f"{path}.{key}"
        _, children = _extract_fields(value, field_path)
        fields.append(
            WorkflowValueField(
                path=field_path,
                label=key.replace("_", " ").title(),
                value_type=_value_type_for_json(value),
                children=children,
            )
        )

    return "object", fields


class HumanTrigger(BaseTrigger):
    config_form = HumanTriggerForm
    input_requirement = WorkflowInputRequirement(
        kind="none",
        label="No input",
        description="Manual test triggers start workflows and do not receive upstream input.",
    )
    
    def execute(self, trigger_data):
        data = self.config.get("data")
        if not data:
            raise NodeExecutionError
        return data


    @classmethod
    def get_output_schema(cls, config=None, input_schema=None):
        data = (config or {}).get("parameters", {}).get("data")
        if data is None:
            return WorkflowIOSchema(
                kind="none",
                label="Human trigger",
            )

        kind, fields = _extract_fields(data)
        
        return WorkflowIOSchema(
            kind=kind,
            label="Human trigger",
            fields=fields
        )
    
    
    