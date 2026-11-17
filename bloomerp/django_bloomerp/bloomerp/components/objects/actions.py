from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext

from bloomerp.components.objects.dataviews.dataview import (
    build_dataview_action_context,
    build_execution_dataview_state,
)
from bloomerp.models.definition import ObjectAction, ObjectActionContext, get_object_actions
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.action_services import (
    ACTION_DATAVIEW_PREFERENCE_PARAM,
    action_is_visible,
    find_executable_action,
)
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.utils.requests import render_message


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

    dataview = None
    if ACTION_DATAVIEW_PREFERENCE_PARAM in request.GET:
        state = build_execution_dataview_state(request, content_type_id)
        if isinstance(state, HttpResponse):
            return state
        dataview = build_dataview_action_context(request, state)
        queryset = dataview.queryset
    else:
        queryset = UserPolicyManager(request.user).get_accessible_queryset(
            model, BloomerpPermission.VIEW,
        )
    obj = get_object_or_404(queryset, pk=object_id)
    context = ObjectActionContext(
        request=request,
        model=model,
        content_type=content_type,
        object=obj,
        surface="dataview_item" if dataview is not None else "detail",
        dataview=dataview,
    )
    if not all(action_is_visible(item, context) for item in (*groups, action)):
        return HttpResponse(status=403)

    response = action.execution_func(context)
    if response is not None:
        return response
    return render_message(
        request, gettext(action.success_message or "Action executed successfully"), "success",
    )
