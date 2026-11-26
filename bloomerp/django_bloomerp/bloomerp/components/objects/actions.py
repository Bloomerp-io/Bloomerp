from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404

from bloomerp.models.actions.object.resolution import get_object_actions
from bloomerp.models.definition import ObjectAction, ObjectActionContext
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.action_services import (
    action_is_visible,
    find_executable_action,
    render_action_success,
)
from bloomerp.utils.models import get_model_and_content_type_or_404


@router.register(
    path="components/objects/actions/<int:content_type_id>/<int_or_uuid:object_id>/<str:action_id>/",
    url_name="components_objects_actions",
)
def actions_execute(
    request: HttpRequest,
    content_type_id: int,
    object_id: str,
    action_id: str,
) -> HttpResponse | StreamingHttpResponse:
    """Execute a configured action for a record visible to the requester."""
    model, content_type = get_model_and_content_type_or_404(content_type_id)
    if model is None:
        raise Http404("Model not found")
    match = find_executable_action(get_object_actions(model, surface="detail"), action_id)
    if match is None:
        raise Http404("Action not found")
    action, groups = match
    if not isinstance(action, ObjectAction) or action.execution_func is None:
        raise Http404("Action not found")
    if request.method != action.method:
        return HttpResponseNotAllowed([action.method])

    queryset = UserPolicyManager(request.user).get_accessible_queryset(
        model, BloomerpPermission.VIEW,
    )
    obj = get_object_or_404(queryset, pk=object_id)
    context = ObjectActionContext(
        request=request,
        model=model,
        content_type=content_type,
        object=obj,
        surface="detail",
    )
    if not all(action_is_visible(item, context) for item in (*groups, action)):
        return HttpResponse(status=403)

    response = action.execution_func(context)
    if response is not None:
        return response
    return render_action_success(
        request, action, content_type_id=content_type_id, object_id=str(object_id),
    )
