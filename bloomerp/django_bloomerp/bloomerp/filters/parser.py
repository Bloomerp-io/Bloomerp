"""Normalize supported input formats into the same filter groups.

Draft API skeleton. Parsing does not compile predicates or decide permissions.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Model
from django.http import QueryDict

from bloomerp.filters.definition import Filters

def parse_filters(args: Mapping[str, Any] | QueryDict, *, model: type[Model]) -> Filters:
    """Parse raw parameters, preserving repeated QueryDict values.

    Planned steps:
    1. Deserialize the optional `filter` JSON parameter.
    2. Parse recognized shorthand parameters using model/lookup metadata.
    3. Append shorthand conditions as an AND group.

    Exact field names take precedence over suffix interpretation. Recognized
    non-filter parameters (pagination, sorting, etc.) are excluded explicitly.
    Malformed filters raise validation errors; they must not disappear.
    Empty input returns no groups. Multiple input formats combine with AND
    when used by ModelFilterManager.
    """
    raise NotImplementedError("Filter input parsing is not implemented yet")


def deserialize_filters(value: str) -> Filters:
    """Validate JSON against list[Filter]; leave lookup-specific cleaning to compilation."""
    raise NotImplementedError("JSON filter deserialization is not implemented yet")


def parse_shorthand_filters(args: Mapping[str, Any] | QueryDict, *, model: type[Model]) -> Filters:
    """Normalize inputs such as first_name_eq=David into ordinary conditions.

    Repeated-value semantics and escaping of ambiguous paths must be defined
    before implementation. Do not flatten QueryDict into a plain dictionary.
    """
    raise NotImplementedError("Shorthand filter parsing is not implemented yet")
