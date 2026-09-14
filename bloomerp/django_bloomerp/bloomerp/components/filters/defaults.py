"""Owner-managed associations between a host preference and saved filters."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from bloomerp.components.filters.common import filter_component, request_parameters
from bloomerp.components.filters.presets import preset_json, preset_scope, validate_preset_filters
from bloomerp.models.filters.filter import SavedFilter
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager


@router.register(path='components/filters/defaults', url_name='components_filters_defaults')
@login_required
@require_POST
@filter_component
def defaults(request: HttpRequest) -> HttpResponse:
    """Adds or removes default filters
    """
    params = request_parameters(request)
    model = {'model': UserListViewPreference, 'workspace': Workspace}.get(params.get('scope'))
    if model is None:
        raise ValidationError('Unknown filter scope')
    with transaction.atomic():
        host = get_object_or_404(model.objects.select_for_update(), pk=params.get('host_id'))
        if not PreferenceManager(request.user).can_manage(host):
            return HttpResponse('Only the owner can change default filters.', status=403)
        scope, identifier = host.get_filter_scope()
        resolver, records, _ = preset_scope(request, {'scope': scope, 'identifier': identifier})
        action = params.get('action')
        if action == 'remove':
            record = get_object_or_404(host.default_filters, pk=params.get('filter_id'))
            host.default_filters.remove(record)
        elif action == 'add':
            groups = validate_preset_filters(params.get('filters'), resolver)
            record = get_object_or_404(records, pk=params['filter_id']) if params.get('filter_id') else None
            # Persist the actual active conditions without overwriting an existing preset.
            if record is None or record.filters != groups:
                index = 1
                while True:
                    record, created = SavedFilter.objects.get_or_create(
                        scope=scope, identifier=identifier, name=f'Filter {index}',
                        defaults={'filters': groups},
                    )
                    if created:
                        break
                    index += 1
            host.add_default_filter(record)
        else:
            raise ValidationError('Unknown default-filter action')
    return JsonResponse(preset_json(record))
