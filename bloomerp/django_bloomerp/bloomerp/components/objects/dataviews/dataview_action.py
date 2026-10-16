from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed

from bloomerp.components.objects.dataviews.dataview import (
    _build_dataview_action_context,
    _build_dataview_state,
    _get_configured_dataview_actions,
)
from bloomerp.models.definition import DataviewAction
from bloomerp.router import router


@router.register(
    path="components/dataview/<int:content_type_id>/action/<str:action_id>/",
    name="components_dataview_action",
)
def configured_dataview_action(
    request: HttpRequest,
    content_type_id: int,
    action_id: str,
) -> HttpResponse:
    """Execute a configured Dataview action against its permission-filtered context."""
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    state = _build_dataview_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state

    action = next(
        (
            configured_action
            for configured_action in _get_configured_dataview_actions(state.model)
            if isinstance(configured_action, DataviewAction)
            and configured_action.id == action_id
        ),
        None,
    )
    if action is None:
        return HttpResponse("Action not found", status=404)
    if request.method != action.method:
        return HttpResponseNotAllowed([action.method])

    action_context = _build_dataview_action_context(request, state)
    try:
        should_execute = action.should_render_func(action_context)
    except Exception:
        should_execute = False
    if not should_execute:
        return HttpResponse(status=403)

    response = action.execution_func(action_context)
    if action.target:
        response["HX-Retarget"] = action.target
    return response
