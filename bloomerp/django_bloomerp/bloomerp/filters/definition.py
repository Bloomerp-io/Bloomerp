from typing import Any, Literal
from pydantic import BaseModel
from pydantic import (
    BaseModel,
    Field
)
from bloomerp.field_types.registry import FieldTypeDefinition


class FilterField(BaseModel):
    field:str
    label:str
    field_type:FieldTypeDefinition
    

class FilterFieldGroup(BaseModel):
    name : str
    fields : list[FilterField] = Field(default_factory=list)


class FilterCondtion(BaseModel):
    field_path:str
    value:Any
    lookup_id:str
    

class Filter(BaseModel):
    connector : Literal["AND", "OR"]
    conditions: list[FilterCondtion] = Field(default_factory=list)
    
    
Filters = list[Filter]
    

