from pydantic import BaseModel


class CanvasTileConfig(BaseModel):
    content:dict # The state of the canvas