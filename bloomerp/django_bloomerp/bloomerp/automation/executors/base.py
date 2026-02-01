
class BaseExecutor:
    """Base class for all executors in the automation system."""
    def __init__(self, config: dict):
        self.config = config
    
    def execute(self, trigger_data: dict) -> dict:
        """Executes the automation logic.
        
        Args:
            trigger_data (dict): The data from the trigger that initiated the automation.
        """
        raise NotImplementedError("Execute method must be implemented by subclasses.")