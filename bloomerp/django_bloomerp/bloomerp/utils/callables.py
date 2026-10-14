"""Resolve typed extension hooks supplied directly or by dotted import path."""

from collections.abc import Callable
from typing import Any, cast

from django.utils.module_loading import import_string


def resolve_hook[Hook: Callable[..., Any]](hook: Hook | str) -> Hook:
    """Resolve an extension hook and reject import paths that are not callable."""
    resolved = import_string(hook) if isinstance(hook, str) else hook
    if not callable(resolved):
        raise TypeError("An extension hook must resolve to a callable.")
    return cast(Hook, resolved)
