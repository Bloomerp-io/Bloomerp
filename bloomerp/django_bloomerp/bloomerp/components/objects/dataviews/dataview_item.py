from uuid import UUID

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django_htmx.http import trigger_client_event

from bloomerp.components.objects.dataviews.dataview import (
    build_dataview_action_context,
    build_execution_dataview_state,
)
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.router import router


@router.register(
    path="components/dataview/<int:content_type_id>/item/<int_or_uuid:object_id>/",
    url_name="components_dataview_item",
)
@require_GET
def dataview_item(request: HttpRequest, content_type_id: int, object_id: int | UUID) -> HttpResponse:
    """Render a record using the originating view's layout, filters, and permissions."""
    try:
        row_index = int(request.headers.get("X-Bloomerp-Dataview-Item-Index", "0"))
    except ValueError:
        return HttpResponseBadRequest("Invalid item index.")
    if row_index < 0:
        return HttpResponseBadRequest("Invalid item index.")

    state = build_execution_dataview_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state
    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is not None and definition.record_based:
        renderer = definition.renderer_cls(state)
        obj = renderer.get_item(str(object_id))
        if obj is not None:
            html = renderer.render_item(
                obj, row_index, build_dataview_action_context(request, state),
                placement=request.headers.get("X-Bloomerp-Dataview-Item-Placement", ""),
            )
            if html is not None:
                return HttpResponse(html)
    return trigger_client_event(
        HttpResponse(status=204), "bloomerp:dataview-refresh", {"result": "saved"},
    )

