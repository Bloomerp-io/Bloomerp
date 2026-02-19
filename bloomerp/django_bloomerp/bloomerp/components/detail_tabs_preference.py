import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404

from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.detail_view_services import get_router_detail_tabs, save_detail_tab_state


def _ensure_all_detail_tabs_in_state(state: dict, available_tabs: list[dict]) -> dict:
    if not isinstance(state, dict):
        return {
            'version': 2,
            'top_level_order': [str(tab.get('key')) for tab in available_tabs if tab.get('key')],
            'folders': [],
            'active': None,
        }

    top_level_order = state.get('top_level_order') or state.get('order') or []
    if not isinstance(top_level_order, list):
        top_level_order = []

    folders = state.get('folders') or []
    if not isinstance(folders, list):
        folders = []

    seen: set[str] = set()

    normalized_top: list[str] = []
    for key in top_level_order:
        if not isinstance(key, str) or not key or key in seen:
            continue
        normalized_top.append(key)
        seen.add(key)

    normalized_folders: list[dict] = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        folder_id = folder.get('id')
        folder_name = folder.get('name')
        tab_order = folder.get('tab_order') or []
        if not isinstance(folder_id, str) or not folder_id:
            continue
        if not isinstance(folder_name, str) or not folder_name.strip():
            folder_name = folder_id
        if not isinstance(tab_order, list):
            tab_order = []

        normalized_order: list[str] = []
        for key in tab_order:
            if not isinstance(key, str) or not key or key in seen:
                continue
            normalized_order.append(key)
            seen.add(key)

        normalized_folders.append({
            'id': folder_id,
            'name': folder_name,
            'tab_order': normalized_order,
        })

    available_keys = [str(tab.get('key')) for tab in available_tabs if tab.get('key')]
    for key in available_keys:
        if key in seen:
            continue
        normalized_top.append(key)
        seen.add(key)

    active = state.get('active') if isinstance(state.get('active'), str) else None
    if active and active not in seen:
        active = normalized_top[0] if normalized_top else None

    return {
        'version': 2,
        'top_level_order': normalized_top,
        'folders': normalized_folders,
        'active': active,
    }


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

    state = _ensure_all_detail_tabs_in_state(state, available_tabs)

    requested_keys: list[str] = []

    top_level_keys = state.get('top_level_order') or state.get('order') or []
    folder_keys: list[str] = []
    for folder in state.get('folders') or []:
        if not isinstance(folder, dict):
            continue
        folder_keys.extend(folder.get('tab_order') or [])

    for key in list(top_level_keys) + folder_keys:
        if isinstance(key, str) and key not in requested_keys:
            requested_keys.append(key)

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
