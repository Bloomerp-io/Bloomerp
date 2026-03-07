import re

from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig
from bloomerp.workspaces.tiles import BaseTileRenderer

class AnalyticsKpiRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/kpi.html"

    def render(self, config:AnalyticsTileConfig):
        value = config.fields.get("value")
        sub_value = config.fields.get("sub_value")

        return self.render_to_string({
            "value": value,
            "sub_value": sub_value
        })
