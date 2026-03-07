from bloomerp.workspaces.tiles import BaseTileRenderer
from bloomerp.workspaces.data_view_tile.model import DataViewTileConfig

class DataViewTileRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/data_view.html"

    def render(self, config: DataViewTileConfig) -> str:
        """
        Render the data view tile based on the provided configuration.

        Args:
            config (DataViewTileConfig): The configuration for the data view tile.

        Returns:
            str: The rendered HTML for the data view tile.
        """
        pass