from bloomerp.automation.base_executor import BaseExecutor
from django import forms

class BaseTrigger(BaseExecutor):
    config_form : forms.Form = None
    
    def execute(self, trigger_data):
        # Triggers just return the raw data
        return trigger_data