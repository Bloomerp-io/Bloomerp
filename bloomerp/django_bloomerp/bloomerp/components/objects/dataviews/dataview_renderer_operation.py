from bloomerp.components.objects.dataviews.dataview import _build_dataview_state
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.router import router
from django.http import HttpRequest, HttpResponse


@router.register(
    path="components/dataview/<int:content_type_id>/renderer-operation/<str:action>/",
    name="components_dataview_renderer_operation",
)
def dataview_action(request: HttpRequest, content_type_id: int, action: str) -> HttpResponse:
    """Dispatches a view-specific dataview action to the active renderer."""
    state = _build_dataview_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state

    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    return definition.renderer_cls.handle_action(action, request, state)
