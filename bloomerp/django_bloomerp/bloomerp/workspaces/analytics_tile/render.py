

from typing import Optional

from django.http import HttpRequest

from bloomerp.services.sql_services import SqlExecutor
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileType
from bloomerp.workspaces.base import BaseTileRenderer


class AnalyticsTileRenderer(BaseTileRenderer):
    @classmethod
    def render(cls, config:AnalyticsTileConfig, request:HttpRequest):
        analytics_tile_type = AnalyticsTileType.from_key(config.type)
        add_fields_message = "<p>Add fields to render</p>"

        if not config.fields:
            return add_fields_message
        
        return analytics_tile_type.render_cls.render(config, request)
