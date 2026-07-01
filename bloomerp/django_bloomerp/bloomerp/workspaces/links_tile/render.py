

from django.http import HttpRequest

from bloomerp.workspaces.links_tile.model import LinkTileConfig
from bloomerp.workspaces.base import BaseTileRenderer

class LinksTileRenderer(BaseTileRenderer):
    template_name = "cotton/features/workspaces/tiles/link.html"
    
    @classmethod
    def render(cls, config, request:HttpRequest):
        return cls.render_to_string(
            {
                "config":config
            }
        )

        
