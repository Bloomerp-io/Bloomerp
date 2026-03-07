

from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileType
from bloomerp.workspaces.tiles import BaseTileRenderer


class AnalyticsTileRenderer(BaseTileRenderer):

    def render(self, config:AnalyticsTileConfig):
        analytics_tile_type = AnalyticsTileType.from_key(config.type)

        return analytics_tile_type.render_cls().render(config)
