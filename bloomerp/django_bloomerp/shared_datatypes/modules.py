from pydantic import BaseModel, Field
from typing import Optional
from typing import Any
from bloomerp.models.base_bloomerp_model import FieldLayout

class PermissionConfig(BaseModel):
    id:str
    name:str


class BaseConfig(BaseModel):
    id: str
    name: str 
    description: Optional[str] = None
    enabled: bool = True


class FieldConfig(BaseConfig):
    type: str
    options: Optional[dict] = None
    validators : list[str] = Field(default_factory=list)

    
class ModelConfig(BaseConfig):
    name_plural: Optional[str] = None
    fields: list[FieldConfig] = Field(default_factory=list)
    custom_permissions: Optional[PermissionConfig] = Field(default_factory=list)
    string_representation: Optional[str] = None
    field_layout: Optional[FieldLayout] = Field(default_factory=FieldLayout)
    

class SubModuleConfig(BaseConfig):
    code: str
    models: list[ModelConfig] = Field(default_factory=list)
    

class ModuleConfig(BaseConfig):
    code: str
    icon: str
    sub_modules: list[SubModuleConfig] = Field(default_factory=list)