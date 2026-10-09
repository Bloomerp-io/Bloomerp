from django.http import HttpRequest, HttpResponse

from bloomerp.components.objects.dataviews.bulk_actions import (
    _build_bulk_action_state,
    _editable_fields,
    _get_selected_field,
    _render_field_selector,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.router import router
from bloomerp.utils.models import get_model_and_content_type_or_404


@router.register(
    path="components/dataview/<int:content_type_id>/bulk_actions/field_selector/",
    url_name="components_bulk_actions_field_selector",
)
def field_selector(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Render a permitted bulk field without interpreting its inputs as filters."""
    state = _build_bulk_action_state(
        request,
        content_type_id,
        BloomerpPermission.BULK_CHANGE,
    )
    if isinstance(state, HttpResponse):
        return state

    model, content_type = get_model_and_content_type_or_404(content_type_id)
    editable_fields = _editable_fields(request, model, content_type)
    application_field = _get_selected_field(request, content_type, editable_fields)
    if application_field is None:
        return HttpResponse("Invalid field", status=400)

    return _render_field_selector(request, application_field)
