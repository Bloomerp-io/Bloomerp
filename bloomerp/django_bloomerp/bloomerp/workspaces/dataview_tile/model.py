from copy import deepcopy
from typing import Self

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from bloomerp.models.users.user_list_view_preference import UserListViewPreference, ViewType

from bloomerp.workspaces.base import BaseTileConfig, TileOperationDefinition, TileOperationHandler, TileOperationHandlerRespone


class DataViewTileConfig(BaseTileConfig):
    content_type_id:int | None = None
    view_type:str = ViewType.TABLE
    fields:list[int] = Field(default_factory=list)
    opts:dict = Field(default_factory=dict)

    @classmethod
    def get_default(cls, *args, **kwargs) -> Self:
        return cls(
            content_type_id=kwargs.get("content_type_id"),
            view_type=kwargs.get("view_type") or ViewType.TABLE,
            fields=list(kwargs.get("fields") or []),
            opts=dict(kwargs.get("opts") or {}),
        )

    @classmethod
    def get_operation(cls, operation: str):
        return {
            "set_content_type_id" : TileOperationDefinition(
                SetContentTypeIdOperation,
                SetContentTypeIdHandler,
            ),
            "set_view_type": TileOperationDefinition(
                SetViewTypeOperation,
                SetViewTypeHandler,
            ),
            "toggle_field": TileOperationDefinition(
                ToggleFieldOperation,
                ToggleFieldHandler,
            ),
        }[operation]


def build_preview_preference(
    base_preference: UserListViewPreference,
    config: DataViewTileConfig,
) -> UserListViewPreference:
    display_fields = deepcopy(base_preference.display_fields or {})
    display_fields[config.view_type] = list(config.fields)

    return UserListViewPreference(
        user=base_preference.user,
        content_type=base_preference.content_type,
        page_size=base_preference.page_size,
        page_type=base_preference.page_type,
        view_type=config.view_type,
        split_view_enabled=base_preference.split_view_enabled,
        kanban_group_by_field=base_preference.kanban_group_by_field,
        calendar_start_field=base_preference.calendar_start_field,
        calendar_end_field=base_preference.calendar_end_field,
        calendar_view_mode=base_preference.calendar_view_mode,
        display_fields=display_fields,
    )
    
class SetContentTypeIdOperation(BaseModel):
    content_type_id:int

class SetContentTypeIdHandler(TileOperationHandler):
    @staticmethod
    def handle(config:DataViewTileConfig, data:SetContentTypeIdOperation):
        config.content_type_id = data.content_type_id
        config.view_type = ViewType.TABLE
        config.fields = []
        config.opts = {}

        return TileOperationHandlerRespone(
            config,
            _("Model updated"),
        )


class SetViewTypeOperation(BaseModel):
    view_type:str


class SetViewTypeHandler(TileOperationHandler):
    @staticmethod
    def handle(config: DataViewTileConfig, data: SetViewTypeOperation):
        if data.view_type not in ViewType.values:
            return TileOperationHandlerRespone(
                config,
                _("Invalid view type"),
                "error",
            )

        config.view_type = data.view_type

        return TileOperationHandlerRespone(
            config,
            _("View updated"),
        )


class ToggleFieldOperation(BaseModel):
    field_id:int


class ToggleFieldHandler(TileOperationHandler):
    @staticmethod
    def handle(config: DataViewTileConfig, data: ToggleFieldOperation):
        field_ids = list(config.fields)

        if data.field_id in field_ids:
            field_ids.remove(data.field_id)
            message = _("Field removed")
        else:
            field_ids.append(data.field_id)
            message = _("Field added")

        config.fields = field_ids

        return TileOperationHandlerRespone(
            config,
            message,
        )
