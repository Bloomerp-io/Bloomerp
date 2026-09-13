from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from bloomerp.components.filters.common import filter_component, resolver_for_request
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.lookups.definition import BoundLookup
from bloomerp.router import router


@router.register(path="components/filters/lookups", url_name="components_filters_lookups")
@login_required
@filter_component
def lookups(request: HttpRequest) -> JsonResponse:
    """Return lookup metadata; a scoped path also checks access and SQL support."""
    params = request.GET
    target = None
    if params.get("scope"):
        field, target = resolver_for_request(request, params).resolve(params.get("field_path"))
        field_type = field.context.field_type
    else:
        field_type = FIELD_TYPE_REGISTRY.from_id(params.get("field_type"))
    definitions = [BoundLookup.normalize(item) for item in field_type.lookups]
    return JsonResponse([
        {"id": lookup.id, "label": lookup.label, "nested": lookup.nested}
        for lookup in definitions
        if target is None or target.backend != "sql"
        or lookup.nested or lookup.get_sql_factory() is not None
    ], safe=False)
