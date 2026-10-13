from collections.abc import Iterator
from typing import Literal, Optional, Self

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from bloomerp.models.workspaces.sidebar_item import is_internal_sidebar_url
from bloomerp.workspaces.base import (
    BaseTileConfig,
    TileOperationDefinition,
    TileOperationHandler,
    TileOperationHandlerRespone,
)


class Link(BaseModel):
    """A navigation link or a folder containing an ordered list of nested items."""

    url: str = Field(
        default="",
        description="Navigation destination: an instance-relative URL such as '/' or an absolute external URL. Use a discovered page URL rather than guessing a route. Ignored for folders.",
    )
    url_name: SkipJsonSchema[str] = Field(
        default="",
        description="Optional route-name metadata. The renderer does not resolve this value into a URL; supply the destination in url.",
    )
    name: str = Field(description="Visible label of the link or folder.")
    icon: str = Field(
        default="",
        description="Font Awesome CSS classes, for example 'fa-solid fa-link'. Empty hides the link icon; folders use a default folder icon.",
    )
    is_internal: SkipJsonSchema[bool] = Field(
        default=False,
        description="Whether the destination supports internal HTMX navigation. The renderer recalculates this from url; it does not control access to the destination.",
    )
    is_folder: bool = Field(
        default=False,
        description="Set true for an expandable folder that displays children instead of navigating to url. Set false for a clickable link.",
    )
    children: list["Link"] = Field(
        default_factory=list,
        description="Ordered nested links or folders. Displayed only when is_folder is true; leave empty for a clickable link.",
    )


class LinkTileConfig(BaseTileConfig):
    """Configuration for a tile displaying navigation links and nested folders."""

    id: SkipJsonSchema[str | None] = None
    links: list[Link] = Field(
        description="Ordered top-level links and folders displayed on the tile. Nest items in a folder's children. This list is required; an empty list creates an empty tile.",
    )

    @classmethod
    def get_default(cls) -> Self:
        """Return a links tile containing an internal Home link."""
        return cls(
            links=[
                Link(
                    url="/",
                    name="Home",
                    is_internal=True,
                )
            ]
        )

    @classmethod
    def get_operation(cls, operation: str) -> TileOperationDefinition:
        """Return the payload model and handler for a supported link editor operation."""
        return {
            "add_link": TileOperationDefinition(AddLinkOperation, AddLinkHandler),
            "add_folder": TileOperationDefinition(AddFolderOperation, AddFolderHandler),
            "remove_link": TileOperationDefinition(RemoveLinkOperation, RemoveLinkHandler),
            "update_link": TileOperationDefinition(UpdateLinkOperation, UpdateLinkHandler),
            "move_link": TileOperationDefinition(MoveLinkOperation, MoveLinkHandler),
        }[operation]


def _get_items_at_path(config: LinkTileConfig, parent_path: list[int]) -> list[Link]:
    """Return the list of items contained by the folder at ``parent_path``."""
    items = config.links
    for index in parent_path:
        if index < 0 or index >= len(items):
            raise ValueError(_("The selected folder no longer exists"))
        folder = items[index]
        if not folder.is_folder:
            raise ValueError(_("Links can only be nested inside folders"))
        items = folder.children
    return items


def _get_item(config: LinkTileConfig, path: list[int]) -> Link:
    """Return one link or folder using its index path."""
    if not path:
        raise ValueError(_("No link was selected"))
    items = _get_items_at_path(config, path[:-1])
    index = path[-1]
    if index < 0 or index >= len(items):
        raise ValueError(_("The selected link no longer exists"))
    return items[index]


def _iter_links(items: list[Link]) -> Iterator[Link]:
    """Yield links and folders from a nested configuration."""
    for item in items:
        yield item
        yield from _iter_links(item.children)


class AddLinkOperation(BaseModel):
    """Payload for appending a navigation link at the root or inside a folder."""

    url: str = Field(description="Nonblank destination URL. A URL already used by a non-folder item anywhere in this tile is rejected.")
    name: Optional[str] = Field(default=None, description="Visible link label. Although nullable in the payload, a nonblank name is required by the handler.")
    icon: str = Field(default="", description="Font Awesome CSS classes for the link icon; empty displays no icon.")
    parent_path: list[int] = Field(default_factory=list, description="Zero-based index path to the destination folder. [] appends at the root; [0, 1] appends inside the second child folder of the first root folder. Every index must identify an existing folder.")


class AddLinkHandler(TileOperationHandler):
    @staticmethod
    def handle(config: LinkTileConfig, data: AddLinkOperation) -> TileOperationHandlerRespone:
        """Add a validated link to the selected folder."""
        name = (data.name or "").strip()
        url = data.url.strip()
        if not name:
            return TileOperationHandlerRespone(config, _("Please add a name to the link"), "warning")
        if not url:
            return TileOperationHandlerRespone(config, _("Please add a URL to the link"), "warning")
        if any(not link.is_folder and link.url == url for link in _iter_links(config.links)):
            return TileOperationHandlerRespone(config, _("Link already existed"), "warning")

        items = _get_items_at_path(config, data.parent_path)
        items.append(
            Link(
                url=url,
                name=name,
                icon=data.icon.strip(),
                is_internal=is_internal_sidebar_url(url),
            )
        )
        return TileOperationHandlerRespone(config, _("Link added"))


class AddFolderOperation(BaseModel):
    """Payload for appending an empty folder at the root or inside another folder."""

    name: str = Field(description="Nonblank visible folder label.")
    icon: str = Field(default="", description="Font Awesome CSS classes for the folder icon; empty uses the default folder icon.")
    parent_path: list[int] = Field(default_factory=list, description="Zero-based index path to the existing parent folder. [] appends at the root; [0] appends inside the first root folder. Every index must identify a folder.")


class AddFolderHandler(TileOperationHandler):
    @staticmethod
    def handle(config: LinkTileConfig, data: AddFolderOperation) -> TileOperationHandlerRespone:
        """Add a folder to the selected nesting level."""
        name = data.name.strip()
        if not name:
            return TileOperationHandlerRespone(config, _("Please add a name to the folder"), "warning")

        items = _get_items_at_path(config, data.parent_path)
        items.append(Link(name=name, icon=data.icon.strip(), is_folder=True))
        return TileOperationHandlerRespone(config, _("Folder added"))


class RemoveLinkOperation(BaseModel):
    """Payload for removing a link or a folder and all its descendants."""

    path: list[int] = Field(description="Nonempty zero-based index path to the existing item to remove. [0] targets the first root item; [0, 1] targets its second child. Removing a folder also removes its entire subtree.")


class RemoveLinkHandler(TileOperationHandler):
    @staticmethod
    def handle(config: LinkTileConfig, data: RemoveLinkOperation) -> TileOperationHandlerRespone:
        """Remove one link or folder subtree by index path."""
        if not data.path:
            raise ValueError(_("No link was selected"))
        items = _get_items_at_path(config, data.path[:-1])
        index = data.path[-1]
        if index < 0 or index >= len(items):
            raise ValueError(_("The selected link no longer exists"))
        items.pop(index)
        return TileOperationHandlerRespone(config, _("Item removed"))


class UpdateLinkOperation(BaseModel):
    """Payload for replacing an item's label and icon and updating a link destination."""

    path: list[int] = Field(description="Nonempty zero-based index path to the existing link or folder. [0] targets the first root item; [0, 1] targets its second child.")
    url: str = Field(default="", description="Replacement destination URL. Must be nonblank when updating a link; ignored for folders.")
    name: str = Field(description="Replacement visible label; must be nonblank for both links and folders.")
    icon: str = Field(default="", description="Replacement Font Awesome CSS classes. Empty clears a link icon or restores the default folder icon.")
    parent_path: list[int] | None = Field(default=None, description="For links only: zero-based path to the destination folder, or [] for the root. null keeps the current parent. Moving to a different parent appends the link there. Paths refer to the configuration before the update; ignored for folders.")


class UpdateLinkHandler(TileOperationHandler):
    @staticmethod
    def handle(config: LinkTileConfig, data: UpdateLinkOperation) -> TileOperationHandlerRespone:
        """Update the selected link or folder without changing its position."""
        item = _get_item(config, data.path)
        name = data.name.strip()
        url = data.url.strip()
        if not name:
            return TileOperationHandlerRespone(config, _("Please add a name"), "warning")
        if not item.is_folder and not url:
            return TileOperationHandlerRespone(config, _("Please add a URL to the link"), "warning")

        source_items = None
        destination_items = None
        if not item.is_folder and data.parent_path is not None:
            source_items = _get_items_at_path(config, data.path[:-1])
            destination_items = _get_items_at_path(config, data.parent_path)

        item.name = name
        item.icon = data.icon.strip()
        if not item.is_folder:
            item.url = url
            item.is_internal = is_internal_sidebar_url(url)
            if source_items is not None and destination_items is not None and source_items is not destination_items:
                source_items.pop(data.path[-1])
                destination_items.append(item)
        return TileOperationHandlerRespone(config, _("Item updated"))


class MoveLinkOperation(BaseModel):
    """Payload for reordering a link or folder among its current siblings."""

    path: list[int] = Field(description="Nonempty zero-based index path to the item to reorder. [0] targets the first root item; [0, 1] targets its second child.")
    direction: Literal["up", "down"] = Field(description="Move one position earlier ('up') or later ('down') among siblings. Does not change the parent; moving past either end leaves the order unchanged.")


class MoveLinkHandler(TileOperationHandler):
    @staticmethod
    def handle(config: LinkTileConfig, data: MoveLinkOperation) -> TileOperationHandlerRespone:
        """Move an item up or down among its current siblings."""
        if not data.path:
            raise ValueError(_("No link was selected"))
        items = _get_items_at_path(config, data.path[:-1])
        index = data.path[-1]
        destination = index - 1 if data.direction == "up" else index + 1
        if index < 0 or index >= len(items) or destination < 0 or destination >= len(items):
            return TileOperationHandlerRespone(config, _("Item cannot be moved further"), "info")

        items[index], items[destination] = items[destination], items[index]
        return TileOperationHandlerRespone(config, _("Item moved"))
