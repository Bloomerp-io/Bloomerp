
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.forms import Form
from django.http import HttpRequest
from pydantic import BaseModel
from typing import TYPE_CHECKING, Literal, Optional, Self, Type
from django import forms
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from bloomerp.models.users.user import User

@dataclass
class TileOperationHandlerRespone:
    config:"BaseTileConfig"
    message:Optional[str]=None
    message_type:Literal["info","success","warning","error"] = "success"

class TileOperationHandler(ABC):
    @staticmethod
    @abstractmethod
    def handle(config:BaseModel, data:BaseModel) -> TileOperationHandlerRespone:
        pass

@dataclass
class TileOperationDefinition:
    validation_model:type[BaseModel]|type[forms.Form]
    handler:TileOperationHandler


class BaseTileConfig(BaseModel):
    @classmethod
    @abstractmethod
    def get_default(cls, *args, **kwargs) -> Self:
        pass

    @classmethod
    @abstractmethod
    def get_operation(cls, operation:str) -> TileOperationDefinition:
        pass


class BaseTileRenderer(ABC):
    template_name: str = ""
    legacy_template_prefix: str = "cotton/workspaces/"
    current_template_prefix: str = "cotton/features/workspaces/"

    @classmethod
    @abstractmethod
    def render(
        cls, 
        config: BaseModel, 
        request:HttpRequest,
        *args, 
        **kwargs
        ) -> str:
        raise NotImplementedError("Subclasses must implement the render method.")

    @classmethod
    def render_to_string(cls, context: dict) -> str:
        template_name = cls.template_name
        if template_name.startswith(cls.legacy_template_prefix):
            template_name = template_name.replace(
                cls.legacy_template_prefix,
                cls.current_template_prefix,
                1,
            )
        return render_to_string(template_name, context)
    
    
    

class TileTypeDefinition(BaseModel):
    name:str
    description:str
    icon:str = "" # Font awesome icon
    form_cls:Type[Form] | None = None
    model:Type[BaseTileConfig] | None = None
    render_cls:Type[BaseTileRenderer] | None = None
