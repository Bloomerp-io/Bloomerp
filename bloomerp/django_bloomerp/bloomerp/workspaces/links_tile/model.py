from pydantic import BaseModel

class LinkTileConfig(BaseModel):
    links:list[str]