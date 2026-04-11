

from bloomerp.workspaces.links_tile.model import LinkTileConfig
from bloomerp.workspaces.base import BaseTileRenderer

class LinksTileRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/link.html"
    
    @classmethod
    def render(cls, config, user):
        return cls.render_to_string(
            {
                "config":config
            }
        )

        