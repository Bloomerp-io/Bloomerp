"""Orchestrate user filtering on a caller-supplied queryset.

Typed filters are executable; raw query-parameter parsing remains a draft.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

from django.db.models import Model, QuerySet
from django.http import QueryDict

from bloomerp.filters.compiler import compile_filters
from bloomerp.filters.definition import Filters
from bloomerp.filters.parser import parse_filters
from bloomerp.lookups.definition import CompiledLookup


class ModelFilterManager:
    """Narrow an existing queryset without requiring a user.

    The caller supplies an authorized queryset when row permissions apply.
    Permission validation of filter dependencies belongs to the caller too.
    No permissions are inferred or checked by this manager.
    """

    def __init__(self, model: type[Model]):
        self.model = model

    def filter(
        self,
        args: Mapping[str, Any] | QueryDict,
        queryset: QuerySet,
    ) -> QuerySet:
        """Parse raw parameters, compile groups with AND, and narrow queryset.

        Example:
            ModelFilterManager(Order).filter(
                request.GET,
                queryset=authorized_orders,
            )

        No model.objects.all() fallback: preserve the caller's row restrictions.
        Parsing and compilation errors propagate to the request/policy adapter.
        """
        filters = parse_filters(args, model=self.model)
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
