from .tile import Tile
from .sql_query import SqlQuery
from .workspace import Workspace
from .tile_on_workspace import TileOnWorkspace
from .sidebar import Sidebar
from .sidebar_item import SidebarItem

Widget = Tile

__all__ = [
    'Tile',
    'Widget',
    'SqlQuery',
    'Workspace',
    'TileOnWorkspace',
    'Sidebar',
    'SidebarItem'
]
