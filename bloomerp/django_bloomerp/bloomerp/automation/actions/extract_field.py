from django import forms

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.schema import WorkflowIOSchema, WorkflowInputRequirement, WorkflowValueField, WorkflowValueType
from bloomerp.automation.utils import get_parameters_from_config
from bloomerp.automation.values import get_path_value

class ExtractFieldConfigForm(forms.Form):
    field_path = forms.CharField(
        required=True,
        label="Field Path",
        help_text="The dot-separated path to the field to extract from the input object. For example: 'customer.name' or 'order.items.0.product_name'."
    )
    
    
class ExtractFieldExecutor(BaseExecutor):
    config_form = ExtractFieldConfigForm
    
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.ANY,
        label="Input Value",
        description="The incoming value can be an object, list, or model-like object with the configured path.",
    )

    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.ANY,
        label="Extracted Value",
        description="The value extracted from the incoming input.",
    )

    @staticmethod
    def _normalize_field_path(field_path: str) -> str:
        return field_path.removeprefix("input.")

    @staticmethod
    def _remap_extracted_fields(
        fields: list[WorkflowValueField],
        extracted_path: str,
    ) -> list[WorkflowValueField]:
        remapped = []
        prefix = f"{extracted_path}."

        for field in fields:
            path = field.path
            if path == extracted_path:
                path = "input"
            elif path.startswith(prefix):
                path = path.removeprefix(prefix)

            remapped.append(
                WorkflowValueField(
                    path=path,
                    label=field.label,
                    value_type=field.value_type,
                    description=field.description,
                    optional=field.optional,
                    children=ExtractFieldExecutor._remap_extracted_fields(
                        field.children,
                        extracted_path,
                    ),
                )
            )

        return remapped
    
    @classmethod
    def accepts_input_schema(cls, incoming_schema, config = None):
        params = get_parameters_from_config(config)
        field_path = params.get("field_path")
        
        if field_path:
            if not incoming_schema or incoming_schema.value_type == WorkflowValueType.NONE:
                return False

            if incoming_schema.value_type == WorkflowValueType.ANY:
                return True

            normalized_path = cls._normalize_field_path(field_path)
            return incoming_schema.get_field_by_path(normalized_path) is not None
            
        return super().accepts_input_schema(incoming_schema, config)
    
    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        params = get_parameters_from_config(config)
        field_path = params.get("field_path")
        normalized_path = cls._normalize_field_path(field_path or "")
        
        field = input_schema.get_field_by_path(normalized_path) if input_schema and normalized_path else None
        if field:
            return WorkflowIOSchema(
                value_type=field.value_type,
                label=field.label,
                description=f"Extracted value from path '{normalized_path}'",
                fields=cls._remap_extracted_fields(field.children, normalized_path),
            )
        
        return super().get_output_schema(config, input_schema)
    
    
    def execute(self, trigger_data):
        params = self.resolve_config(trigger_data)
        
        field_path = params.get("field_path")
        
        if not field_path:
            raise ValueError("Field path is required in the configuration.")

        return get_path_value(trigger_data, self._normalize_field_path(field_path))
