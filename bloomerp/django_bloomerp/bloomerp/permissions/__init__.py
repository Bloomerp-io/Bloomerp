"""Public permission definitions and policy managers."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AccessRule": "definition",
    "BloomerpPermission": "definition",
    "BloomerpPermissionDefinition": "definition",
    "PermissionMatch": "definition",
    "PermissionScope": "definition",
    "PolicyManager": "manager",
    "UserPolicyManager": "manager",
    "create_permission_str": "manager",
}


def __getattr__(name: str) -> Any:
    """Resolve public permission symbols without importing models during app loading."""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)


__all__ = [
    "AccessRule",
    "BloomerpPermission",
    "BloomerpPermissionDefinition",
    "PermissionMatch",
    "PermissionScope",
    "PolicyManager",
    "UserPolicyManager",
    "create_permission_str",
]
