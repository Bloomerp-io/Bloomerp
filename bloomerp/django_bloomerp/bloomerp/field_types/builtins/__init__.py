"""Explicit registration of built-in field types.

Application consumers can import FIELD_TYPE_REGISTRY from bloomerp.field_types
for the populated global registry. Code importing the raw registry module must
call load_builtin_field_types() explicitly.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.field_types.registry import FieldTypeRegistry


def register_builtin_field_types(registry: "FieldTypeRegistry") -> None:
    """Register each built-in field family for discovery and filter compilation."""
    from . import boolean, labels, numeric, other, relations, temporal, text

    for module in (text, numeric, boolean, temporal, relations, other, labels):
        module.register(registry)
