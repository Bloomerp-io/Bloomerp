"""Normalize query parameters into filters, without compiling or authorizing them."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Model
from django.http import QueryDict
from pydantic import TypeAdapter, ValidationError as SchemaValidationError

from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.filters.resolver import FilterFieldResolver
from bloomerp.lookups.definition import BoundLookup


# Endpoint-specific controls must be removed by the caller before parsing.
NON_FILTER_PARAMETERS = frozenset({
    "q", "search", "page", "page_size", "limit", "offset", "ordering", "sort",
    "format", "_component_id",
})
_FILTERS_ADAPTER = TypeAdapter(Filters)


def _items(args):
    if isinstance(args, QueryDict):
        for key, values in args.lists():
            for value in values:
                yield key, value
    else:
        yield from args.items()


def parse_filters(args: Mapping[str, Any] | QueryDict, *, model: type[Model]) -> Filters:
    """Combine JSON groups and shorthand with implicit AND between groups.

    Repeated `filter` parameters each contribute their groups. Repeated shorthand
    parameters each contribute a condition (AND); dictionary lists remain one
    value. Use JSON to express OR or structured values in a URL.
    """
    groups = []
    for key, value in _items(args):
        if key == "filter":
            groups.extend(deserialize_filters(value))
    groups.extend(parse_shorthand_filters(args, model=model))
    return groups


def deserialize_filters(value: str) -> Filters:
    """Read a JSON list of Filter groups; value cleaning belongs to compilation."""
    if not isinstance(value, str):
        raise ValidationError("The filter parameter must be a JSON string")
    try:
        return _FILTERS_ADAPTER.validate_json(value, strict=True)
    except SchemaValidationError as exc:
        raise ValidationError(f"Invalid filter JSON: {exc}") from exc


def _lookup(field, expression):
    matches = {
        bound.id: bound
        for lookup in field.context.field_type.lookups
        for bound in [BoundLookup.normalize(lookup)]
        if not bound.nested and (expression in bound.expressions or expression == bound.id)
    }
    if len(matches) > 1:
        raise ValidationError(f"Ambiguous lookup expression: {expression!r}")
    return next(iter(matches.values()), None)


def _resolve_parameter(resolver, key):
    # Prefer complete field paths, including JSON keys, over suffix parsing.
    try:
        field, _ = resolver.resolve(key)
    except ValidationError:
        pass
    else:
        lookup = _lookup(field, "")
        if lookup is None:
            raise ValidationError(f"Field {key!r} has no default lookup")
        return key, lookup.id

    # Try the longest field path first. Lookup aliases may themselves contain
    # underscores (including aliases such as count__gt).
    for index in reversed(range(1, len(key))):
        if key[index] != "_" or key[index - 1] == "_":
            continue
        separator = 2 if key[index:index + 2] == "__" else 1
        path, expression = key[:index], key[index + separator:]
        if not expression:
            continue
        try:
            field, _ = resolver.resolve(path)
        except ValidationError:
            continue
        lookup = _lookup(field, expression)
        if lookup is not None:
            return path, lookup.id
    raise ValidationError(f"Unknown filter field or lookup: {key!r}")


def parse_shorthand_filters(args: Mapping[str, Any] | QueryDict, *, model: type[Model]) -> Filters:
    """Resolve bare fields and registered lookup suffixes into one AND group.

    `first_name`, `first_name_eq`, and `first_name__exact` select the default
    equality lookup. Unknown parameters fail rather than silently dropping a
    constraint. Reserved controls are ignored; JSON can address those fields.
    """
    resolver = FilterFieldResolver.for_model(model)
    conditions = []
    for key, value in _items(args):
        if key == "filter" or key in NON_FILTER_PARAMETERS:
            continue
        if not isinstance(key, str) or not key:
            raise ValidationError("Filter parameter names must be nonempty strings")
        path, lookup_id = _resolve_parameter(resolver, key)
        conditions.append(FilterCondition(field_path=path, lookup_id=lookup_id, value=value))
    return [Filter(connector="AND", conditions=conditions)] if conditions else []
