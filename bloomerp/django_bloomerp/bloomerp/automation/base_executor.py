from typing import Type

from django import forms
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema, flatten_schema_fields
from bloomerp.automation.values import resolve_parameters

class BaseExecutor:
    """Base class for all executors in the automation system."""
    config_form : Type[forms.Form] = None
    input_requirement = WorkflowInputRequirement(value_type="any")
    output_schema = WorkflowIOSchema(value_type="any")

    def __init__(self, config: dict):
        self.raw_config : dict = config or {}
        self.config : dict = self.raw_config.get("parameters") or {}

    def resolve_config(self, input_data: dict) -> dict:
        return resolve_parameters(self.config, input_data)

    @classmethod
    def get_input_requirement(cls, config: dict | None = None) -> WorkflowInputRequirement:
        return cls.input_requirement

    @classmethod
    def accepts_input_schema(cls, incoming_schema: WorkflowIOSchema | None, config: dict | None = None) -> bool:
        return cls.get_input_requirement(config).accepts(incoming_schema)

    @classmethod
    def get_input_schema(cls, config: dict | None = None) -> WorkflowInputRequirement:
        return cls.get_input_requirement(config)

    @classmethod
    def get_output_schema(
        cls,
        config: dict | None = None,
        input_schema: WorkflowIOSchema | None = None,
    ) -> WorkflowIOSchema:
        return cls.output_schema

    def execute(self, trigger_data: dict) -> dict:
        """Executes the automation logic.

        Args:
            trigger_data (dict): The data from the trigger that initiated the automation.
        """
        raise NotImplementedError("Execute method must be implemented by subclasses.")

    @classmethod
    def get_config_form(cls, *args, **kwargs) -> type[forms.Form] | forms.Form:
        if args or kwargs:
            return cls.config_form(*args, **kwargs)
        return cls.config_form
    
    
class NodeExecutionError(ValueError):
    pass
