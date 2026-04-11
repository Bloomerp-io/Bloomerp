from pydantic import BaseModel
from typing import Optional, Self

from bloomerp.models.workspaces.sidebar_item import is_internal_sidebar_url
from bloomerp.workspaces.base import BaseTileConfig, TileOperationDefinition, TileOperationHandler, TileOperationHandlerRespone
from django.utils.translation import gettext_lazy as _


class Link(BaseModel):
    url:str
    name:str
    is_internal:bool=False

class LinkTileConfig(BaseTileConfig):
    links:list[Link]

    @classmethod
    def get_default(cls) -> Self:
        return cls(
            links=[
                Link(
                    url="/",
                    name="Home",
                    is_internal=True
                )
            ]
        )
    
    @classmethod
    def get_operation(cls, operation):
        return {
            "add_link" : TileOperationDefinition(
                AddLinkOperation, 
                AddLinkHandler
            ),
            "remove_link" : TileOperationDefinition(
                RemoveLinkOperation,
                RemoveLinkHandler
            ),
            "update_link" : TileOperationDefinition(
                AddLinkOperation,
                UpdateLinkHandler
            )
        }[operation]

# ------------------------
# State management
# ------------------------

# Add operation
class AddLinkOperation(BaseModel):
    url:str
    name:Optional[str] = None

class AddLinkHandler(TileOperationHandler):

    @staticmethod
    def handle(config:"LinkTileConfig", data:AddLinkOperation):
        if data.name == "":
            return TileOperationHandlerRespone(
                config,
                _("Please add a name to the link"),
                "warning"
            )

        links = config.links
        for link in links:
            if link.url == data.url:
                return TileOperationHandlerRespone(config, _("Link already existed"), "warning")

        links.append(
            Link(url=data.url, name=data.name, is_internal=is_internal_sidebar_url(data.url))
        )
        config.links = links
        return TileOperationHandlerRespone(
            config,
            ""
        )
    

# Remove operation
class RemoveLinkOperation(BaseModel):
    url:str

class RemoveLinkHandler(TileOperationHandler):
    @staticmethod
    def handle(config:LinkTileConfig, data:RemoveLinkOperation):
        new_links = []
        for link in config.links:
            if link.url != data.url:
                new_links.append(link)
        config.links = new_links
        return TileOperationHandlerRespone(config, _("Link removed"))
        
# Update operation
class UpdateLinkHandler(TileOperationHandler):
    @staticmethod
    def handle(config:LinkTileConfig, data:AddLinkOperation):

        for link in config.links:
            if link.url == data.url:
                link.name = data.name

            if link.name == data.name:
                link.url = data.url

        return TileOperationHandlerRespone(
            config,
            ""
        )

