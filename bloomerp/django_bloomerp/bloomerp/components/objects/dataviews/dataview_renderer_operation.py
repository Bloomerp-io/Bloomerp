from bloomerp.components.objects.dataviews.dataview import _build_dataview_state
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
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
    available_preference = get_object_or_404(
        PreferenceManager(request.user).get_available(
            UserListViewPreference,
            {"content_type_id": content_type_id},
        ),
        Q(pk=preference_id) | Q(source_object_id=preference_id),
    )
    preference = available_preference.effective_preference

    state = _build_dataview_state(
        request,
        content_type_id,
        preference=preference,
    )
    if isinstance(state, HttpResponse):
        return state

    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    return definition.renderer_cls.handle_action(action, request, state)
