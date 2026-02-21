import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404

from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.detail_view_services import (
    get_ordered_tab_keys_from_state,
    get_router_detail_tabs,
    save_detail_tab_state,
)


@router.register(
    path='components/detail_tabs_preference/',
    name='components_detail_tabs_preference',
)
def detail_tabs_preference(request: HttpRequest) -> HttpResponse:
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    content_type_id = request.POST.get('content_type_id')
    if not content_type_id:
        return HttpResponse('Missing content_type_id', status=400)

    try:
        content_type_id = int(content_type_id)
    except ValueError:
        return HttpResponse('Invalid content_type_id', status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id)
    preference = UserDetailViewPreference.get_or_create_for_user(request.user, content_type)

    model = content_type.model_class()
    available_tabs = get_router_detail_tabs(model) if model else []

    state_raw = request.POST.get('state')
    if not state_raw:
        return HttpResponse('Missing state', status=400)

    try:
        state = json.loads(state_raw)
    except json.JSONDecodeError:
        return HttpResponse('Invalid state payload', status=400)

    requested_keys = get_ordered_tab_keys_from_state(state)

    existing_keys = {str(tab.get('key')) for tab in available_tabs if tab.get('key')}
    for key in requested_keys:
        if key in existing_keys:
            continue
        available_tabs.append({
            'key': key,
            'url': key,
            'name': key,
            'requires_pk': False,
        })

    normalized = save_detail_tab_state(
        preference=preference,
        tabs=available_tabs,
        state=state,
    )

    return JsonResponse({'status': 'ok', 'tab_state': normalized})
