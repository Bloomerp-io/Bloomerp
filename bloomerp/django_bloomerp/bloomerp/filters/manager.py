"""Orchestrate strict or explicitly recoverable user filtering on a supplied queryset."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Model, QuerySet
from django.http import QueryDict
from pydantic import ValidationError as SchemaValidationError

from bloomerp.filters.compiler import compile_condition, compile_filters
from bloomerp.filters.definition import Filter, FilterCondition, Filters
from bloomerp.filters.parser import parse_filters
from bloomerp.lookups.definition import CompiledLookup

FilterValidator = Callable[[Filters], None]


class ModelFilterManager:
    """Narrow an existing queryset, optionally recovering interactive user input.

    Callers retain responsibility for row permissions and supply a dependency
    validator when field/relation authorization applies. Recovery is opt-in;
    policy definitions and other strict consumers keep their existing failures.
    """

    def __init__(self, model: type[Model]) -> None:
        """Bind parsing and compilation to the caller's model."""
        self.model = model

    def parse(
        self,
        args: Mapping[str, Any] | QueryDict,
        *,
        recover: bool = False,
        validate_filters: FilterValidator | None = None,
    ) -> Filters:
        """Return effective groups, optionally omitting invalid or denied input.

        Recovery isolates each parameter, JSON group and condition. It preserves
        valid siblings and explicit empty groups, but drops groups emptied by
        rejected conditions. Authorize each condition before value cleaning,
        which may query related records. Never use recovery for policy rules.
        """
        if not recover:
            filters = parse_filters(args, model=self.model)
            if validate_filters is not None:
                validate_filters(filters)
            return filters

        json_groups: Filters = []
        shorthand_conditions: list[FilterCondition] = []
        items = (
            [(key, value) for key, values in args.lists() for value in values]
            if isinstance(args, QueryDict)
            else args.items()
        )
        for key, value in items:
            if key == "filter":
                json_groups.extend(self._recover_json(value))
                continue
            try:
                groups = parse_filters({key: value}, model=self.model)
            except ValidationError:
                continue
            for group in groups:
                shorthand_conditions.extend(group.conditions)
        if shorthand_conditions:
            json_groups.append(Filter(connector="AND", conditions=shorthand_conditions))

        effective: Filters = []
        for group in json_groups:
            conditions: list[FilterCondition] = []
            for condition in group.conditions:
                try:
                    if validate_filters is not None:
                        validate_filters([Filter(connector=group.connector, conditions=[condition])])
                    compile_condition(condition, model=self.model)
                except (PermissionDenied, ValidationError):
                    continue
                conditions.append(condition)
            if conditions or not group.conditions:
                effective.append(group.model_copy(update={"conditions": conditions}))
        return effective

    @staticmethod
    def _recover_json(value: Any) -> Filters:
        """Salvage valid JSON siblings without guessing malformed group semantics."""
        if not isinstance(value, str):
            return []
        try:
            raw_groups = json.loads(value)
        except (ValueError, TypeError):
            return []
        if not isinstance(raw_groups, list):
            return []
        groups: Filters = []
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue
            raw_conditions = raw_group.get("conditions", [])
            if not isinstance(raw_conditions, list):
                continue
            try:
                group = Filter.model_validate({**raw_group, "conditions": []}, strict=True)
            except SchemaValidationError:
                continue
            conditions: list[FilterCondition] = []
            for raw_condition in raw_conditions:
                try:
                    conditions.append(FilterCondition.model_validate(raw_condition, strict=True))
                except SchemaValidationError:
                    continue
            if conditions or not raw_conditions:
                groups.append(group.model_copy(update={"conditions": conditions}))
        return groups

    def filter(
        self,
        args: Mapping[str, Any] | QueryDict,
        queryset: QuerySet,
        *,
        recover: bool = False,
        validate_filters: FilterValidator | None = None,
    ) -> QuerySet:
        """Parse parameters and narrow the original, caller-authorized queryset.

        Errors propagate by default. Interactive boundaries can explicitly opt
        into recovery and supply their existing dependency authorization check.
        """
        filters = self.parse(args, recover=recover, validate_filters=validate_filters)
        return self.apply(filters, queryset=queryset)

    def apply(self, filters: Filters, queryset: QuerySet) -> QuerySet:
        """Compile already parsed filters with implicit AND between groups.

        Callers can parse parameters and validate filter permissions before
        passing the same filters here. An empty list leaves queryset unchanged.
        """
        if queryset.model is not self.model:
            raise ValueError("Queryset model does not match the filter manager")

        if not filters:
            return queryset

        compiled = compile_filters(
            filters,
            model=self.model,
            connector="AND",
        )
        return self._apply(queryset, compiled)

    @staticmethod
    def _apply(queryset: QuerySet, compiled: CompiledLookup) -> QuerySet:
        """Attach annotations, apply the positional Q predicate, then distinct.

        Must operate on the supplied queryset throughout and avoid colliding
        with its existing annotations. No query is evaluated by this method.
        """
        queryset = queryset.annotate(**compiled.annotations) if compiled.annotations else queryset
        queryset = queryset.filter(compiled.predicate)
        return queryset.distinct() if compiled.distinct else queryset
