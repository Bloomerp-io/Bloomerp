from bloomerp.components.objects.dataviews.dataview import (
    DATAVIEW_OPERATION_CONTEXT_PARAM,
    _build_dataview_state,
    _resolve_dataview_preference,
)
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.router import router
from django.http import HttpRequest, HttpResponse


@router.register(
    path=(
        "components/dataview/<int:content_type_id>/preference/"
        "<int:preference_id>/renderer-operation/<str:action>/"
    ),
    name="components_dataview_renderer_operation",
)
def dataview_action(
    request: HttpRequest,
    content_type_id: int,
    preference_id: int,
    action: str,
) -> HttpResponse:
    """Dispatch an operation to the renderer of an available preference."""
    preference = _resolve_dataview_preference(
        request,
        content_type_id=content_type_id,
        preference_id=preference_id,
    )

    definition = DATAVIEW_REGISTRY.get(preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    state = _build_dataview_state(
        request,
        content_type_id,
        preference=preference,
        calculate_count=definition.renderer_cls.action_requires_count(action),
    )
    if isinstance(state, HttpResponse):
        return state
    state.operation_context_token = request.GET.get(
        DATAVIEW_OPERATION_CONTEXT_PARAM
    )

    return definition.renderer_cls.handle_action(action, request, state)
