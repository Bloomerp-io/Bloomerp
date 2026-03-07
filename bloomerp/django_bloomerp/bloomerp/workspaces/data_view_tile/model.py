from pydantic import BaseModel


class DataViewTileConfig(BaseModel):
    content_type_id:int
    view_type:str
    fields:list[int] # The list of application fields to display
    opts:dict # Additional options for the data view tile