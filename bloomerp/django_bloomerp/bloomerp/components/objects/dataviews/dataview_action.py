from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, StreamingHttpResponse
from django.utils.translation import gettext

from bloomerp.components.objects.dataviews.dataview import (
    build_dataview_action_context,
    build_execution_dataview_state,
)
from bloomerp.models.actions.dataview.builtins import get_dataview_actions
from bloomerp.models.definition import DataviewAction
from bloomerp.router import router
from bloomerp.services.action_services import (
    action_is_visible,
    find_executable_action,
    render_action_success,
)


@router.register(
    path="components/dataview/<int:content_type_id>/action/<str:action_id>/",
    name="components_dataview_action",
)
def configured_dataview_action(
    request: HttpRequest,
    content_type_id: int,
    action_id: str,
) -> HttpResponse | StreamingHttpResponse:
    """Execute a configured Dataview action against its permission-filtered context."""
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    state = build_execution_dataview_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state

    match = find_executable_action(get_dataview_actions(state.model), action_id)
    if match is None:
        return HttpResponse("Action not found", status=404)
    action, groups = match
    if not isinstance(action, DataviewAction) or action.execution_func is None:
        return HttpResponse("Action not found", status=404)
    if request.method != action.method:
        return HttpResponseNotAllowed([action.method])

    context = build_dataview_action_context(request, state)
    if not all(action_is_visible(item, context) for item in (*groups, action)):
        return HttpResponse(status=403)
    if not context.selected_ids and any(item.requires_selection for item in (*groups, action)):
        return HttpResponse(gettext("Select at least one record."), status=400)

    response = action.execution_func(context)
    if response is not None:
        return response
    return render_action_success(request, action, content_type_id=content_type_id)
