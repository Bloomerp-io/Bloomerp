"""Resolve and validate conditions once, then compile through registered lookups."""
from __future__ import annotations

import json
import re
from functools import reduce
from operator import and_, or_
from typing import Any, Literal
from uuid import UUID, uuid4

from django import forms
from django.core.exceptions import EmptyResultSet, ValidationError
from django.db import connections, DEFAULT_DB_ALIAS
from django.db.models import BooleanField, Exists, Expression, F, Model, OuterRef, Q

from bloomerp.filters.definition import FilterCondition, FilterField, Filters
from bloomerp.filters.resolver import FilterExecutionTarget, FilterFieldResolver, resolve_lookup
from bloomerp.lookups.definition import BoundLookup, CompiledLookup, CompiledSQL, SQLLookupContext

Connector = Literal["AND", "OR"]


def _combine(items, connector):
    if connector not in {"AND", "OR"}:
        raise ValidationError("Invalid filter connector")
    if not items:
        return Q(pk__isnull=False) if connector == "AND" else Q(pk__in=[])
    return reduce(or_ if connector == "OR" else and_, items)


def resolve_condition(
    condition: FilterCondition, *, model: type[Model] | None = None,
    resolver: FilterFieldResolver | None = None,
) -> tuple[FilterField, FilterExecutionTarget, BoundLookup, Any]:
    """Resolve structure and clean the value; callers handle authorization."""
    if resolver is None:
        if model is None:
            raise ValueError("Supply a model or field resolver")
        resolver = FilterFieldResolver.for_model(model)
    field, target = resolver.resolve(condition.field_path)
    lookup = resolve_lookup(field, target, condition.lookup_id)
    if lookup.nested:
        raise ValidationError("A nested lookup cannot be the terminal condition")
    factory = lookup.get_form_factory()
    form_field = factory(field.context) if factory else field.context.get_form_field()
    value = condition.value
    # JSONField.clean expects its serialized input, not a native JSON scalar.
    if isinstance(form_field, forms.JSONField):
        value = json.dumps(value)
    if isinstance(form_field, forms.BooleanField) and isinstance(value, str):
        normalized = value.lower().strip()
        if normalized not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValidationError("Invalid boolean filter value")
        value = normalized in {"true", "1", "yes", "on"}
    cleaned = form_field.clean(value)
    # ModelChoiceField produces a model; the factories receive a scalar key.
    if isinstance(cleaned, Model):
        cleaned = cleaned.pk
    elif isinstance(cleaned, (list, tuple)):
        cleaned = [item.pk if isinstance(item, Model) else item for item in cleaned]
    return field, target, lookup, cleaned


def compile_condition(condition: FilterCondition, *, model: type[Model]) -> CompiledLookup:
    field, target, lookup, value = resolve_condition(condition, model=model)
    factory = lookup.get_q_factory()
    if factory is None:
        raise ValidationError("Lookup does not support Django filtering")
    annotations = {}
    path = target.field_path
    if target.orm_expression is not None:
        path = f"_filter_{uuid4().hex}"
        annotations[path] = target.orm_expression
    compiled = factory(field.context.application_field, path, lookup.expressions[0], value)
    annotations.update(compiled.annotations)
    if annotations or compiled.distinct:
        # Isolate lookup-local aliases and aggregates from each other and from
        # annotations already on the caller's queryset.
        matches = model._base_manager.filter(pk=OuterRef("pk")).annotate(**annotations).filter(compiled.predicate)
        return CompiledLookup(predicate=Q(Exists(matches)))
    return compiled


def compile_filters(filters: Filters, *, model: type[Model], connector: Connector = "AND") -> CompiledLookup:
    """Compile groups; no filters is a caller decision, never an implicit grant."""
    if not filters:
        raise ValidationError("Empty filter collections are handled by the caller")
    groups = [
        _combine([compile_condition(condition, model=model).predicate for condition in group.conditions], group.connector)
        for group in filters
    ]
    return CompiledLookup(predicate=_combine(groups, connector))


class _SQLLookupPredicate(Expression):
    """Let Django resolve joins; let the registered SQL factory build the predicate."""
    output_field = BooleanField()

    def __init__(self, lhs, lookup, value, context):
        super().__init__()
        self.lhs, self.lookup, self.value, self.context = lhs, lookup, value, context

    def get_source_expressions(self):
        return [self.lhs]

    def set_source_expressions(self, expressions):
        self.lhs, = expressions

    def as_sql(self, compiler, connection):
        from dataclasses import replace

        lhs_sql, lhs_params = compiler.compile(self.lhs)
        # Preserve the order even when a factory repeats a parameterized JSON
        # expression alongside its own value placeholders.
        prefix = f"__filter_lhs_{uuid4().hex}_"
        for index in range(len(lhs_params)):
            lhs_sql = lhs_sql.replace("%s", f"{prefix}{index}__", 1)
        result = self.lookup.get_sql_factory()(
            replace(self.context, field_path=lhs_sql), self.lookup.expressions[0], self.value,
        )
        values = iter(result.parameters)
        params = []

        def substitute(match):
            params.append(lhs_params[int(match.group(1))] if match.group(1) is not None else next(values))
            return "%s"

        clause = re.sub(rf"{prefix}(\d+)__|%s", substitute, result.clause)
        if not connection.features.has_native_uuid_field:
            params = [value.hex if isinstance(value, UUID) else value for value in params]
        return clause, params


def compile_sql_filters(
    filters: Filters, *, model: type[Model], connector: Connector = "AND",
    using: str = DEFAULT_DB_ALIAS,
) -> CompiledSQL:
    """Return a parameterized predicate for the model's table, including joins.

    The surrounding SELECT must use the model's physical table name. This is
    predicate compilation, not authorization or arbitrary-query rewriting.
    Aggregate SQL factories need a separate HAVING contract and are rejected.
    """
    from bloomerp.filters.utils import resolve_model_path

    if not filters:
        raise ValidationError("Empty filter collections are handled by the caller")
    connection = connections[using]
    groups = []
    for group in filters:
        predicates = []
        for condition in group.conditions:
            field, target, lookup, value = resolve_condition(condition, model=model)
            if lookup.get_sql_factory() is None:
                raise ValidationError("Lookup does not support SQL filtering")
            _, model_field, keys = resolve_model_path(model, target.field_path)
            if model_field.one_to_many or model_field.many_to_many:
                raise ValidationError("SQL collection filtering requires an aggregate/subquery contract")
            context = SQLLookupContext(
                field_path=target.field_path,
                sql_type=model_field.db_type(connection),
                # A non-null terminal column can still be NULL through a LEFT JOIN.
                nullable=model_field.null or "__" in target.field_path,
                dialect={"postgresql": "postgres"}.get(connection.vendor, connection.vendor),
            )
            lhs = target.orm_expression if target.orm_expression is not None else F(target.field_path)
            predicates.append(Q(_SQLLookupPredicate(lhs, lookup, value, context)))
        groups.append(_combine(predicates, group.connector))
    predicate = _combine(groups, connector)
    queryset = model._base_manager.using(using).filter(predicate).order_by().values_list("pk", flat=True)
    try:
        sql, params = queryset.query.get_compiler(using=using).as_sql()
    except EmptyResultSet:
        return CompiledSQL(clause="1 = 0")
    quote = connection.ops.quote_name
    return CompiledSQL(
        clause=f"{quote(model._meta.db_table)}.{quote(model._meta.pk.column)} IN ({sql})",
        parameters=tuple(params),
    )


def compile_sql_field_filters(filters: Filters, *, resolver: FilterFieldResolver) -> CompiledSQL:
    """Compile configured result columns using the same lookup validation as models."""
    def combine(items, connector):
        if connector not in {"AND", "OR"}:
            raise ValidationError("Invalid filter connector")
        if not items:
            return CompiledSQL(clause="TRUE" if connector == "AND" else "FALSE")
        return CompiledSQL(
            clause=(f" {connector} ").join(f"({item.clause})" for item in items),
            parameters=tuple(value for item in items for value in item.parameters),
        )

    groups = []
    for group in filters:
        predicates = []
        for condition in group.conditions:
            _, target, lookup, value = resolve_condition(condition, resolver=resolver)
            if target.backend != "sql" or target.sql_context is None:
                raise ValidationError("Expected a configured SQL result column")
            factory = lookup.get_sql_factory()
            if factory is None:
                raise ValidationError("Lookup does not support SQL filtering")
            predicates.append(factory(target.sql_context, lookup.expressions[0], value))
        groups.append(combine(predicates, group.connector))
    return combine(groups, "AND")
