"""Scope and validation shared by saved-preset endpoints."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from pydantic import TypeAdapter, ValidationError as SchemaValidationError

from bloomerp.filters.compiler import clean_lookup_value, compile_condition
from bloomerp.filters.definition import Filter, Filters
from bloomerp.filters.resolver import FilterFieldResolver, resolve_lookup
from bloomerp.models.filters.filter import SavedFilter


def preset_scope(request, params):
    scope, identifier = params.get("scope"), params.get("identifier")
    if not isinstance(identifier, (str, int)) or isinstance(identifier, bool) or not str(identifier).strip():
        raise ValidationError("A scope identifier is required")
    resolver = FilterFieldResolver.for_user(scope, identifier, request.user)
    identifier = str(resolver.workspace.pk if resolver.workspace is not None else ContentType.objects.get_for_model(resolver.model).pk)
    return resolver, SavedFilter.objects.filter(scope=scope, identifier=identifier), identifier


def preset_record(queryset, identifier):
    if not identifier:
        raise ValidationError("A saved filter ID is required")
    return get_object_or_404(queryset, pk=identifier)


def validate_preset_filters(value, resolver):
    try:
        filters = TypeAdapter(Filters).validate_python(value, strict=True)
    except SchemaValidationError as exc:
        raise ValidationError("Invalid grouped filters") from exc
    for group in filters:
        for condition in group.conditions:
            for field, target in resolver.resolve_all(condition.field_path):
                lookup = resolve_lookup(field, target, condition.lookup_id)
                cleaned = clean_lookup_value(field, lookup, condition.value)
                if target.backend == "django":
                    local = condition.model_copy(update={"field_path": target.field_path})
                    resolver.policy_manager.validate_filters(target.model, [Filter(connector="AND", conditions=[local])])
                    compile_condition(local, model=target.model)
                else:
                    lookup.get_sql_factory()(target.sql_context, lookup.expressions[0], cleaned)
    return [group.model_dump(mode="json") for group in filters]


def preset_json(record):
    return {"id": str(record.pk), "name": record.name, "scope": record.scope,
            "identifier": record.identifier, "filters": record.filters}
