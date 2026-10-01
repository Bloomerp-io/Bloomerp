from django.http import HttpRequest

from bloomerp.mcp.definition import McpTool
from bloomerp.mcp.schema import serializer_input_schema, serializer_output_schema
from bloomerp.router import router
from rest_framework import serializers

class PageItemSerializer(serializers.Serializer):
    title = serializers.CharField()
    clickable = serializers.BooleanField()

class GetCurrentPageOutputSerializer(serializers.Serializer):
    url = serializers.CharField()
    items = serializers.ListSerializer()

@router.register(
    name="Get current page",
    description="Returns the current page the user is on including the page items which can be clicked",
    route_type="mcp",
    mcp=McpTool(
        input_schema=serializer_input_schema(serializers.Serializer),
        output_schema=serializer_output_schema(GetCurrentPageOutputSerializer)
    )
)
def get_current_page(request:HttpRequest):
    """Navigates a user to a paricular page

    Args:
        request (HttpRequest): Returns the 

    Returns:
        _type_: _description_
    """
    # 1. Use the websocket connection and call for the current page
    
    
    
    return {
        "status" : "success",
    }