from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse

from bloomerp.components.filters.common import filter_component, resolver_for_request
from bloomerp.router import router


def filterable_field_type_ids():
    """Shared by existing model-field selectors outside the filter builder."""
    from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
    return [field_type.id for field_type in FIELD_TYPE_REGISTRY.values() if field_type.lookups]


@router.register(path="components/filters/fields", url_name="components_filters_fields")
@login_required
@filter_component
def fields(request: HttpRequest) -> JsonResponse:
    """Discover root fields or children of field_path through lookup_id."""
    params = request.GET
    groups = resolver_for_request(request, params).discover(
        params.get("field_path"), params.get("lookup_id"),
    )
    return JsonResponse(
        [group.model_dump(mode="json") for group in groups],
        safe=False,
    )
