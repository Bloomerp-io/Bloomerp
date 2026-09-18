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


def __getattr__(name: str) -> Any:
    """Load registry exports lazily to avoid Django model import cycles."""
    if name not in _REGISTRY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    registry = import_module("bloomerp.dataviews.registry")
    return getattr(registry, name)


__all__ = [
    "BaseDataview",
    "BaseDataviewRenderer",
    "DATAVIEW_REGISTRY",
    "DataviewPagination",
    "DataviewRegistry",
    "DataviewState",
    "DataviewTypeDefinition",
    "PageSize",
    "application_field_choices",
    "application_field_name_choices",
    "get_dataview_type_choices",
    "page_size_choices",
    "register_dataview",
]
