
from re import L
from typing import Literal

from django.contrib import messages
from django.contrib.messages import constants

class MessageMixin:
    def render_to_response(self, context, **response_kwargs):
        context["xyz_template_name"] = self.template_name
        self.template_name = "message_template.html"
        return super().render_to_response(context, **response_kwargs)
    
    def add_message(self, text:str, type:Literal['info', 'warning', 'danger', 'success']):
        """Add's a message

        Args:
            text (str): the text to render
            type (Literal[&#39;info&#39;, &#39;warning&#39;, &#39;danger&#39;, &#39;success&#39;]): the message type
        """
        match type:
            case "success":
                level = constants.SUCCESS
            case "warning":
                level = constants.WARNING
            case "danger":
                level = constants.ERROR
            case _:
                level = constants.INFO
                
        messages.add_message(
            request=self.request,
            level=level,
            message=text,
        )