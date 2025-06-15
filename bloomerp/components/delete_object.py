from bloomerp.utils.router import route
from django.http import HttpRequest, HttpResponse
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required

from bloomerp.services.permission_services import has_access_to_object


@login_required
@route('delete_object')
def delete_object(request: HttpRequest) -> HttpResponse:
    """Delete a single object."""
    if request.method != 'POST':
        return HttpResponse('Invalid request', status=405)

    content_type_id = request.GET.get('content_type_id')
    object_id = request.POST.get('object_id')

    if not content_type_id or not object_id:
        return HttpResponse('content_type_id and object_id required', status=400)

    content_type = get_object_or_404(ContentType, pk=content_type_id)
    model = content_type.model_class()

    obj = get_object_or_404(model, pk=object_id)
    user = request.user

    if not has_access_to_object(user, obj):
        return HttpResponse('Permission denied', status=403)

    obj.delete()
    return HttpResponse('Object deleted')
