from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from bloomerp.components.filters.common import filter_component
from bloomerp.components.filters.presets import preset_json, preset_scope
from bloomerp.router import router


@router.register(path="components/filters/get", url_name="components_filters_get")
@login_required
@require_GET
@filter_component
def get(request: HttpRequest) -> JsonResponse:
    _, records, _ = preset_scope(request, request.GET)
    return JsonResponse([preset_json(record) for record in records], safe=False)
    
