from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from pydantic import BaseModel, Field
from typing import Optional
from bloomerp.models import mixins


class LayoutItem(BaseModel):
    id: int | str
    colspan: int = 1


class LayoutRow(BaseModel):
    columns: int
    items: list[LayoutItem] = Field(default_factory=list)
    title: Optional[str] = None


class FieldLayout(BaseModel):
    rows: list[LayoutRow] = Field(default_factory=list)


class BloomerpModel(
    mixins.TimestampedModelMixin,
    mixins.StringSearchModelMixin,
    mixins.UserStampedModelMixin,
    mixins.AbsoluteUrlModelMixin,
    mixins.AvatarModelMixin,
    models.Model,
):
    class Meta:
        abstract = True
        default_permissions = (
            'add', 
            'change', 
            'delete', 
            'view', 
            'bulk_change', 
            'bulk_delete', 
            'bulk_add', 
            'export'
        )
    
    files = GenericRelation("bloomerp.File")
    comments = GenericRelation("bloomerp.Comment")

    field_layout:Optional[FieldLayout] = None
    form_layout:dict = None # DEPR 


    
