from typing import TYPE_CHECKING, Any, Type

from django import forms
from bloomerp.automation.ports import (
    DEFAULT_OUTPUT_PORT,
    WorkflowNodeOutputPort,
    validate_output_ports,
)
from bloomerp.automation.results import DeferResult, PreparedInput
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowIOSchema
from bloomerp.automation.values import resolve_parameters

if TYPE_CHECKING:
    from bloomerp.automation.runtime import WorkflowNodeExecutionContext

class BaseExecutor:
    """Base class for all executors in the automation system."""
    config_form : Type[forms.Form] = None
    input_requirement = WorkflowInputRequirement(value_type="any")
    output_schema = WorkflowIOSchema(value_type="any")
    output_ports: tuple[WorkflowNodeOutputPort, ...] = ()

    def __init__(self, parameters: dict):
        self.config: dict = parameters or {}

    def resolve_config(self, input_data: dict) -> dict:
        return resolve_parameters(self.config, input_data)

    def prepare(
        self,
        input_data: Any,
        context: "WorkflowNodeExecutionContext",
    ) -> PreparedInput | DeferResult:
        """Prepare runtime input before ``execute``.

        Most executors should not override this. Join-style executors may
        return ``DeferResult`` until all required inputs are available.
        """
        return PreparedInput(input_data=input_data)

    @classmethod
    def get_output_ports(
        cls,
        config: dict | None = None,
    ) -> tuple[WorkflowNodeOutputPort, ...]:
        """Return declared ports, or an implicit unlimited default port."""
        ports = validate_output_ports(cls.output_ports)
        return ports or (DEFAULT_OUTPUT_PORT,)

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
        port_id: str = "default",
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
