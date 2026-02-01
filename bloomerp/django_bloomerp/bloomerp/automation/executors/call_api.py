from .base import BaseExecutor
import requests
        
class CallApiExecutor(BaseExecutor):
    """Executor for calling external APIs as part of the automation workflow."""
    
    def execute(self, input_data: dict, config: dict) -> dict:
        """Executes the API call based on the provided configuration.
        
        Args:
            input_data (dict): The data from the trigger that initiated the automation.
            config (dict): The configuration for the API call, including endpoint, method, headers, and payload.
        """
        
        endpoint = config.get("endpoint")
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        payload = config.get("payload", {})
        
        response = requests.request(method, endpoint, headers=headers, json=payload)
        
        # Handle response as needed (e.g., logging, error handling)
        if response.status_code >= 200 and response.status_code < 300:
            print(f"API call successful: {response.status_code}")
        else:
            print(f"API call failed: {response.status_code} - {response.text}")
            
    