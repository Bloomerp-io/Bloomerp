from shared_utils.router.component_router import route
from django.http import HttpRequest, HttpResponse
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required

from bloomerp.services.permission_services import has_object_permission
from bloomerp.constants.permissions import BasePermission
from bloomerp.utils.request_utils import render_blank_form
from bloomerp.utils.request_utils import get_object_from_request

@login_required
@route('delete_object')
def delete_object(request: HttpRequest) -> HttpResponse:
    """Delete a single object.
    """
    object, obj_id, ct_id = get_object_from_request(request)
    
    if not object:
        return HttpResponse('content_type_id and object_id required', status=400)

    user = request.user

    if not has_object_permission(user, object, BasePermission.DELETE):
        return HttpResponse('Permission denied', status=403)

    if request.method == "GET":
        return render_blank_form(
            request,
            None,
            {"object_id":obj_id, "content_type_id":ct_id}
        )
    elif request.method == "POST":
        object.delete()
        return HttpResponse('Object deleted')

