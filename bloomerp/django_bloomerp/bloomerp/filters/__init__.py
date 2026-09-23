"""Public filter definitions and compilation helpers."""

from importlib import import_module
from typing import Any

from bloomerp.filters.definition import (
    Filter,
    FilterCondition,
    FilterField,
    FilterFieldGroup,
    Filters,
)


def __getattr__(name: str) -> Any:
    """Resolve filter helpers only when application code requests them."""
    if name == "ModelFilterManager":
        return getattr(import_module(f"{__name__}.manager"), name)
    if name == "compile_filters":
        return getattr(import_module(f"{__name__}.compiler"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Filter", "FilterCondition", "FilterField", "FilterFieldGroup", "Filters",
    "ModelFilterManager", "compile_filters",
]
