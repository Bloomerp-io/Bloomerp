"""Public form behavior definitions and action catalog."""

from importlib import import_module
from typing import Any

_DEFINITION_EXPORTS = {
    "BehaviorAction", "BehaviorActionDefinition", "BehaviorConfig", "BehaviorContext",
    "BehaviorFieldReference", "BehaviorMessage", "BehaviorResult", "FieldStateUpdate",
    "FieldValueUpdate", "FormBehavior",
}
_BUILTIN_EXPORTS = {
    "BUILTIN_ACTIONS", "CALCULATE", "CLEAR_VALUE", "COPY_FIELD_VALUE", "FETCH",
    "INCREMENT_O2M_VALUE", "POPULATE_WEEK_DATES", "SET_FIELD_INTERACTION",
    "SET_FIELD_VISIBILITY", "SET_O2M_VALUE", "SET_USER_FIELD_TO_CURRENT_USER",
    "SET_VALUE", "SHOW_MESSAGE", "TRANSFORM_TEXT",
}


def __getattr__(name: str) -> Any:
    """Load behavior definitions and built-ins when requested by a caller."""
    if name in _DEFINITION_EXPORTS:
        module = import_module(f"{__name__}.definition")
    elif name == "ACTION_REGISTRY":
        module = import_module(f"{__name__}.registry")
    elif name in _BUILTIN_EXPORTS:
        module = import_module(f"{__name__}.builtins")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(module, name)


__all__ = [
    "ACTION_REGISTRY",
    "BUILTIN_ACTIONS",
    "CALCULATE",
    "CLEAR_VALUE",
    "COPY_FIELD_VALUE",
    "FETCH",
    "INCREMENT_O2M_VALUE",
    "POPULATE_WEEK_DATES",
    "SET_FIELD_INTERACTION",
    "SET_FIELD_VISIBILITY",
    "SET_O2M_VALUE",
    "SET_USER_FIELD_TO_CURRENT_USER",
    "SET_VALUE",
    "SHOW_MESSAGE",
    "TRANSFORM_TEXT",
    "BehaviorAction",
    "BehaviorActionDefinition",
    "BehaviorConfig",
    "BehaviorContext",
    "BehaviorFieldReference",
    "BehaviorMessage",
    "BehaviorResult",
    "FieldStateUpdate",
    "FieldValueUpdate",
    "FormBehavior",
]
