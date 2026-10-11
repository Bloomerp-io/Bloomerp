



from typing import Any

class BaseIMAdapter:
    def validate_connection(self) -> bool:
        """Validates the connection

        Returns:
            bool: _description_
        """
    
    def send_message(self):
        pass
    
    def receive_message(self):
        pass
    
    


class InstantMessagingTypeDefinition:
    name:str
    description:str
    adapter:Any
    
    
    
