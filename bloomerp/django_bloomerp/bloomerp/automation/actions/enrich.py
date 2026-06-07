

from bloomerp.automation.base_executor import BaseExecutor


class EnrichExecutor(BaseExecutor):
    
    
    def execute(self, trigger_data):
        if isinstance(trigger_data, list):
            pass
        
        
        return super().execute(trigger_data)