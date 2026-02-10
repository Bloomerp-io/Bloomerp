from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from pydantic import BaseModel, Field
from typing import Optional
from bloomerp.models import mixins

class LayoutSection(BaseModel):
    columns: int
    items: list[str | int] = Field(default_factory=list)
    title: Optional[str] = None
    
class FieldLayout(BaseModel):
    sections: list[LayoutSection] = Field(default_factory=list)


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


    
