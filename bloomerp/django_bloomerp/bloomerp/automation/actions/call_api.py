from random import choices

from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from ..base_executor import BaseExecutor
import requests
import json
from django import forms

class CallApiForm(forms.Form):
    endpoint = forms.CharField(
        max_length=1000,
    )
    method = forms.CharField(
        choices=[("GET", "GET"), ("POST", "POST")]
    )
    headers = forms.JSONField(
        widget=CodeEditorWidget(
            language="json"
        )
    )
    payload = forms.JSONField(
        widget=CodeEditorWidget(
            language="json"
        )
    ) 

        
class CallApiExecutor(BaseExecutor):
    """Executor for calling external APIs as part of the automation workflow."""
    config_form = CallApiForm    
        
    def execute(self, input_data: dict) -> dict:
        """Executes the API call based on the provided configuration.
        
        Args:
            input_data (dict): The data from the trigger that initiated the automation.
            config (dict): The configuration for the API call, including endpoint, method, headers, and payload.
        """
        endpoint = self.config.get("endpoint")
        method = self.config.get("method", "GET").upper()
        headers = self.config.get("headers", {})
        payload = self.config.get("payload", {})
        
        response = requests.request(method, endpoint, headers=headers, json=payload)
        
        # Handle response as needed (e.g., logging, error handling)
        if response.status_code >= 200 and response.status_code < 300:
            return json.loads(response.content)
        else:
            print(f"API call failed: {response.status_code} - {response.text}")
            return {}
            
    