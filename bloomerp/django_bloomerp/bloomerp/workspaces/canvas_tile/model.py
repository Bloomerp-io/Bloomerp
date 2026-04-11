from pydantic import BaseModel

from bloomerp.workspaces.base import BaseTileConfig


class CanvasTileConfig(BaseTileConfig):
    content:dict # The state of the canvas

    @classmethod
    def get_default(cls, *args, **kwargs):
        return CanvasTileConfig(
            content={}
        )
    
    @classmethod
    def get_operation(cls, operation):
        return {}

