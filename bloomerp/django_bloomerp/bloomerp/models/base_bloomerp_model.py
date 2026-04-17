from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from pydantic import BaseModel, Field
from typing import Optional
from bloomerp.models.mixins.absolute_url_model_mixin import AbsoluteUrlModelMixin
from bloomerp.models.mixins.avatar_model_mixin import AvatarModelMixin
from bloomerp.models.mixins.string_search_model_mixin import StringSearchModelMixin
from bloomerp.models.mixins.timestamp_model_mixin import TimestampModelMixin
from bloomerp.models.mixins.user_stamp_model_mixin import UserStampModelMixin
from bloomerp.models.mixins.uuid_model_mixin import UuidModelMixin


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
    UuidModelMixin,
    TimestampModelMixin,
    StringSearchModelMixin,
    UserStampModelMixin,
    AbsoluteUrlModelMixin,
    AvatarModelMixin,
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


    
