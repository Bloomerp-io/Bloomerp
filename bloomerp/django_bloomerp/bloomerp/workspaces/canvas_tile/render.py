from bloomerp.workspaces.base import BaseTileRenderer
from bloomerp.workspaces.canvas_tile.model import CanvasTileConfig

class CanvasTileRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/canvas.html"

    @classmethod
    def render(cls, config: CanvasTileConfig, user) -> str:
        """
        Render the canvas tile based on the provided configuration.

        Args:
            config (CanvasTileConfig): The configuration for the canvas tile.

        Returns:
            str: The rendered HTML for the canvas tile.
        """
        context = {
            "content": config.content
        }
        return cls.render_to_string(context)