"""Public lookup definitions, registry, and built-in catalog."""

from importlib import import_module
from typing import Any

from bloomerp.lookups.definition import (
    BoundLookup,
    CompiledLookup,
    CompiledSQL,
    FilterFieldContext,
    LookupDefinition,
    SQLLookupContext,
)
from bloomerp.lookups.registry import LOOKUP_REGISTRY, LookupRegistry


def __getattr__(name: str) -> Any:
    """Expose the built-in lookup catalog on demand."""
    if name == "BUILTIN_LOOKUPS":
        return getattr(import_module(f"{__name__}.builtins"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BUILTIN_LOOKUPS",
    "LOOKUP_REGISTRY",
    "BoundLookup",
    "CompiledLookup",
    "CompiledSQL",
    "FilterFieldContext",
    "LookupDefinition",
    "LookupRegistry",
    "SQLLookupContext",
]
