"""Authoring references built from installed definitions without executing nodes."""

from enum import Enum
from pathlib import Path
from typing import Any


from django.http import HttpRequest
from django.utils.functional import Promise


SENSITIVE_NAMES = (
    "password",
    "secret",
    "token",
    "api_key",
    "credential",
    "authorization",
)


def sensitive_name(name: str) -> bool:
    """Identify credential-bearing fields or nested default keys for omission."""
    return any(part in name.lower() for part in SENSITIVE_NAMES)


def literal_metadata(value: Any) -> Any:
    """Copy JSON literals without evaluating callables, querysets or arbitrary objects."""
    if isinstance(value, Promise):
        return str(value)
    if isinstance(value, Enum):
        return literal_metadata(value.value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    if type(value) in (list, tuple):
        return [literal_metadata(item) for item in value]
    if type(value) is dict:
        return {
            key: None if sensitive_name(key) else literal_metadata(item)
            for key, item in value.items()
            if type(key) is str
        }
    return None


def packaged_guide(name: str) -> str:
    """Load a fixed packaged guide filename selected by a resource provider."""
    return (Path(__file__).parent / "resources" / name).read_text(encoding="utf-8")




