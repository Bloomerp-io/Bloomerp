from bloomerp.automation.executors.base import BaseExecutor

class BaseTrigger(BaseExecutor):
    config_form = None
    
    def execute(self, trigger_data):
        # Triggers just return the raw data
        return trigger_data