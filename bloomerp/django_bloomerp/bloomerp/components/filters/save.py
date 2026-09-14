from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_POST

from bloomerp.components.filters.common import filter_component, request_parameters
from bloomerp.components.filters.presets import preset_json, preset_record, preset_scope, validate_preset_filters
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.router import router


@router.register(path="components/filters/save", url_name="components_filters_save")
@login_required
@require_POST
@filter_component
def save(request: HttpRequest) -> JsonResponse:
    params = request_parameters(request)
    resolver, records, identifier = preset_scope(request, params)
    name = params.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("A filter name is required")
    filters = validate_preset_filters(params.get("filters"), resolver)
    updating = "filter_id" in params
    try:
        with transaction.atomic():
            record = preset_record(records.select_for_update(), params["filter_id"]) if updating else SavedFilter(scope=params["scope"], identifier=identifier)
            if updating and (
                record.workspace_defaults.exclude(user=request.user).exists()
                or record.userlistviewpreference_defaults.exclude(user=request.user).exists()
            ):
                return JsonResponse({'error': 'Only the owner can change a default filter.'}, status=403)
            record.name, record.filters = name.strip(), filters
            record.save()
    except IntegrityError as exc:
        raise ValidationError("A filter with that name already exists in this scope") from exc
    return JsonResponse(preset_json(record), status=200 if updating else 201)
