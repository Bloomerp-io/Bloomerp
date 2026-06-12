from random import choices

from bloomerp.automation.schema import WorkflowIOSchema, WorkflowValueField, WorkflowValueType
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
        initial="GET",
        widget=forms.Select(choices=[("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("DELETE", "DELETE")])
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
    
    output_schema = WorkflowIOSchema(
        value_type=WorkflowValueType.OBJECT,
        label="API Response",
        description="The response from the API call, including status code and response data.",
        fields=[
            WorkflowValueField(
                path="status_code",
                value_type=WorkflowValueType.NUMBER,
                label="Status Code",
                description="The HTTP status code returned by the API."
            ),
            WorkflowValueField(
                path="response",
                value_type=WorkflowValueType.ANY,
                label="Response Data",
                description="The data returned by the API.",
            ),
            WorkflowValueField(
                path="status",
                value_type=WorkflowValueType.STRING,
                label="Status",
                description="Indicates whether the API call was successful or if there was an error."
            ),
        ]
    )
    
    
    def execute(self, input_data: dict) -> dict:
        """Executes the API call based on the provided configuration.
        
        Args:
            input_data (dict): The data from the trigger that initiated the automation.
            config (dict): The configuration for the API call, including endpoint, method, headers, and payload.
        """
        params = self.resolve_config(input_data)
        
        # Extract parameters from the configuration
        endpoint = params.get("endpoint")
        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        payload = params.get("payload", {})
        
        try:
            response = requests.request(method, endpoint, headers=headers, json=payload)
            
            # Handle response as needed (e.g., logging, error handling)
            if response.status_code >= 200 and response.status_code < 300:
                # Try to parse JSON response, if applicable
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = response.text
                
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "response": response_data,
                }
            else:
                try:
                    response_data = response.json()
                except json.JSONDecodeError:
                    response_data = response.text

                return {
                    "status" : "error",
                    "status_code": response.status_code,
                    "response": response_data,
                }
        except Exception as e:
            return {
                "status": "error",
                "status_code": None,
                "response": str(e),
            }
    