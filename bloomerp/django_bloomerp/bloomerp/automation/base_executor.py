from django import forms

class BaseExecutor:
    """Base class for all executors in the automation system."""
    config_form : forms.Form = None

    def __init__(self, config: dict):
        self.config : dict = config.get("parameters")

    def execute(self, trigger_data: dict) -> dict:
        """Executes the automation logic.

        Args:
            trigger_data (dict): The data from the trigger that initiated the automation.
        """
        raise NotImplementedError("Execute method must be implemented by subclasses.")


class NodeExecutionError(ValueError):
    pass