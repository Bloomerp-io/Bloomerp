"""Public API for defining and registering Bloomerp dataviews."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from bloomerp.dataviews.definition import (
    BaseDataview,
    BaseDataviewRenderer,
    DataviewPagination,
    DataviewState,
    DataviewTypeDefinition,
    PageSize,
    application_field_choices,
    application_field_name_choices,
    page_size_choices,
)

if TYPE_CHECKING:
    from bloomerp.dataviews.registry import (
        DATAVIEW_REGISTRY,
        DataviewRegistry,
        get_dataview_type_choices,
        register_dataview,
    )

_REGISTRY_EXPORTS = {
    "DATAVIEW_REGISTRY",
    "DataviewRegistry",
    "get_dataview_type_choices",
    "register_dataview",
}

_CONFIG_EXPORTS = {
    "CalendarDataView": "calendar.config",
    "CardDataView": "card.config",
    "FileBrowserDataview": "file_browser.config",
    "GanttDataView": "gant.config",
    "KanbanDataView": "kanban.config",
    "PivotTableDataView": "pivot_table.config",
    "TableDataView": "table.config",
}


def __getattr__(name: str) -> Any:
    """Load registry and built-in configs lazily to avoid model import cycles."""
    if name in _REGISTRY_EXPORTS:
        module_name = "registry"
    elif name in _CONFIG_EXPORTS:
        module_name = _CONFIG_EXPORTS[name]
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f"{__name__}.{module_name}")
    return getattr(module, name)


__all__ = [
    "DATAVIEW_REGISTRY",
    "BaseDataview",
    "BaseDataviewRenderer",
    "CalendarDataView",
    "CardDataView",
    "DataviewPagination",
    "DataviewRegistry",
    "DataviewState",
    "DataviewTypeDefinition",
    "FileBrowserDataview",
    "GanttDataView",
    "KanbanDataView",
    "PageSize",
    "PivotTableDataView",
    "TableDataView",
    "application_field_choices",
    "application_field_name_choices",
    "get_dataview_type_choices",
    "page_size_choices",
    "register_dataview",
]
