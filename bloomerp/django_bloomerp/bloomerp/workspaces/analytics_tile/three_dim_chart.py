from __future__ import annotations

from typing import TYPE_CHECKING

from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig


class AnalyticsThreeDimChartRenderer(BaseTileRenderer):

    @classmethod
    def render(cls, config: AnalyticsTileConfig, user):
        pass