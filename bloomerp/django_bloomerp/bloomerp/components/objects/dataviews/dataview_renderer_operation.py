from bloomerp.components.objects.dataviews.dataview import (
    DATAVIEW_OPERATION_CONTEXT_PARAM,
    _build_dataview_state,
    _valid_dataview_operation_context,
)
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404


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
    available_preference = (
        PreferenceManager(request.user).get_available(
            UserListViewPreference,
            {"content_type_id": content_type_id},
        )
        .filter(Q(pk=preference_id) | Q(source_object_id=preference_id))
        .first()
    )
    if available_preference is not None:
        preference = available_preference.effective_preference
    elif _valid_dataview_operation_context(
        request,
        content_type_id=content_type_id,
        preference_id=preference_id,
    ):
        preference = get_object_or_404(
            UserListViewPreference,
            pk=preference_id,
            content_type_id=content_type_id,
        )
    else:
        raise Http404

    state = _build_dataview_state(
        request,
        content_type_id,
        preference=preference,
    )
    if isinstance(state, HttpResponse):
        return state
    state.operation_context_token = request.GET.get(
        DATAVIEW_OPERATION_CONTEXT_PARAM
    )

    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    return definition.renderer_cls.handle_action(action, request, state)
