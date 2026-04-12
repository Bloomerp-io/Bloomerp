from .tile import Tile
from .sql_query import SqlQuery
from .workspace import Workspace
from .sidebar import Sidebar
from .sidebar_item import SidebarItem

Widget = Tile

__all__ = [
    'Tile',
    'Widget',
    'SqlQuery',
    'Workspace',
    'Sidebar',
    'SidebarItem'
]
