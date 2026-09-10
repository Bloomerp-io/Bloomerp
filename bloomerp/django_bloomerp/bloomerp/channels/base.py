from channels.generic.websocket import AsyncJsonWebsocketConsumer

class BaseBloomerpConsumer(AsyncJsonWebsocketConsumer):
    """Stream workflow-run events to authorized workflow builders."""
    
    
    
    