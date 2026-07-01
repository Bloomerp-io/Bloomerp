

from django.http import HttpRequest
from bloomerp.workspaces.base import BaseTileRenderer

class FormTileRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/link.html"
    
    @classmethod
    def render(cls, config, request:HttpRequest):
        return cls.render_to_string(
            {
                "config":config
            }
        )

        
