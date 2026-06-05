from pydantic import BaseModel
from typing import Optional, Self

from bloomerp.models.forms.form import Form
from bloomerp.models.workspaces.sidebar_item import is_internal_sidebar_url
from bloomerp.workspaces.base import BaseTileConfig, TileOperationDefinition, TileOperationHandler, TileOperationHandlerRespone
from django.utils.translation import gettext_lazy as _
from django import forms

class FormTileConfig(BaseTileConfig):
    form_id:str

    @classmethod
    def get_default(cls) -> Self:
        return cls(
            form_id="123"
        )
    
    @classmethod
    def get_operation(cls, operation):
        return {
            "set_form" : TileOperationDefinition(
                FormTileForm, 
                SetFormHandler
            ),
        }[operation]

class FormTileForm(forms.Form):
    form = forms.ModelChoiceField(
        queryset=Form.objects.all()
    )


class SetFormHandler(TileOperationHandler):
    @staticmethod
    def handle(config:"FormTileConfig", data:FormTileForm):
        
        
        if data.is_valid():
            form = data.cleaned_data["form"]
            
            
            return TileOperationHandlerRespone(
                config,
                "Hello",
                "success"
            )
        
        return TileOperationHandlerRespone(
            config,
            "Error occured",
            "warning",
        )
