from bloomerp.components.objects.dataviews.dataview import _build_dataview_state, _build_dataview_action_context, _get_configured_dataview_actions
from bloomerp.models.definition import DataviewAction
from bloomerp.router import router

from django.http import HttpRequest, HttpResponse


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
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

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

    action_context = _build_dataview_action_context(request, state)
    try:
        should_execute = action.should_render_func(action_context)
    except Exception:
        should_execute = False
    if not should_execute:
        return HttpResponse(status=403)

    return action.execution_func(action_context)
