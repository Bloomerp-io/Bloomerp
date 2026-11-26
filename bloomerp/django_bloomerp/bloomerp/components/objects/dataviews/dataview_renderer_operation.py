from django.http import Http404, HttpRequest, HttpResponse

from bloomerp.components.objects.dataviews.dataview import (
    _build_dataview_state,
    get_context_dataview_token,
    resolve_dataview_preference,
)
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.router import router


@router.register(
    re_path=(
        r"^components/dataview/(?P<content_type_id>[0-9]+)/"
        r"(?:preference/(?P<preference_id>[0-9]+)/)?renderer-operation/(?P<action>[^/]+)/$"
    ),
    name="components_dataview_renderer_operation",
)
def dataview_action(
    request: HttpRequest,
    content_type_id: str,
    action: str,
    preference_id: str | None = None,
) -> HttpResponse:
    """Dispatch an operation using the view's saved or signed layout."""
    content_type_pk = int(content_type_id)
    signed_layout = get_context_dataview_token(request, content_type_pk) is not None
    if preference_id is None and not signed_layout:
        raise Http404("A signed calendar layout is required")

    preference = None
    if preference_id is not None and not signed_layout:
        preference = resolve_dataview_preference(request, content_type_pk, int(preference_id))

    state = _build_dataview_state(
        request,
        content_type_pk,
        preference=preference,
        renderer_action=action,
    )
    if isinstance(state, HttpResponse):
        return state
    expected_preference_id = preference.pk if preference is not None else (
        int(preference_id) if preference_id is not None else None
    )
    if state.preference.pk != expected_preference_id or (
        preference_id is None and state.preference.view_type != "calendar"
    ):
        raise Http404("Dataview layout does not match the renderer operation")
    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    return definition.renderer_cls.handle_action(action, request, state)
