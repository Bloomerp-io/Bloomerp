from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router


@router.register(
    path='components/detail_tabs_folder_modal/',
    name='components_detail_tabs_folder_modal',
)
def detail_tabs_folder_modal(request: HttpRequest) -> HttpResponse:
    if request.method not in {'GET', 'POST'}:
        return HttpResponse('Method not allowed', status=405)

    mode = request.GET.get('mode') if request.method == 'GET' else request.POST.get('mode')
    mode = mode if mode in {'create', 'rename'} else 'create'

    content_type_id = request.GET.get('content_type_id') if request.method == 'GET' else request.POST.get('content_type_id')
    if not content_type_id:
        return HttpResponse('Missing content_type_id', status=400)

    try:
        content_type_id_int = int(content_type_id)
    except ValueError:
        return HttpResponse('Invalid content_type_id', status=400)

    content_type = get_object_or_404(ContentType, id=content_type_id_int)
    UserDetailViewPreference.get_or_create_for_user(request.user, content_type)

    folder_id = request.GET.get('folder_id', '') if request.method == 'GET' else request.POST.get('folder_id', '')
    initial_name = request.GET.get('folder_name', '') if request.method == 'GET' else request.POST.get('folder_name', '')

    context: dict = {
        'mode': mode,
        'content_type_id': content_type_id_int,
        'folder_id': folder_id,
        'folder_name': initial_name,
        'success': False,
        'error': None,
        'result_folder_name': None,
    }

    if request.method == 'POST':
        submitted_name = (request.POST.get('folder_name') or '').strip()
        if not submitted_name:
            context['error'] = 'Folder name is required.'
        else:
            context['success'] = True
            context['result_folder_name'] = submitted_name
            context['folder_name'] = submitted_name

    return render(request, 'components/detail_tabs/folder_modal_form.html', context)
