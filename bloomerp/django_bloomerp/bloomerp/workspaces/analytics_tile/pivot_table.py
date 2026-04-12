from __future__ import annotations

from typing import TYPE_CHECKING

from bloomerp.workspaces.base import BaseTileRenderer

if TYPE_CHECKING:
    from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig

class AnalyticsPivotTableRenderer(BaseTileRenderer):

    @classmethod
    def render(cls, config: AnalyticsTileConfig, user):
        pass