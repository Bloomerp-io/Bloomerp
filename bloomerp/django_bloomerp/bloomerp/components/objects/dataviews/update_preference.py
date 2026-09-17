from django.middleware.csrf import get_token
from pydantic import ValidationError as PydanticValidationError

from bloomerp.components.objects.dataviews.dataview import _get_accessible_application_fields, _get_dataview_options_form
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.models import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.user_services import get_data_view_fields, toggle_field_visibility
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
import json


def _change_data_view_field_visibility(
    request: HttpRequest,
    content_type: ContentType,
    preference: UserListViewPreference,
    post_data,
) -> HttpResponse | None:
    try:
        field_id = int(post_data["toggle_field_id"])
        view_type = post_data.get("toggle_view_type", preference.view_type)
        if DATAVIEW_REGISTRY.get(view_type) is None:
            return HttpResponse("Invalid view type", status=400)

        permission_manager = UserPolicyManager(request.user)
        application_field = ApplicationField.objects.get(id=field_id)

        if not permission_manager.has_field_permission(
            application_field,
            BloomerpPermission.VIEW
        ):
            return HttpResponse("Permission denied", status=403)

        toggle_field_visibility(request.user, content_type, field_id, view_type)
        # toggle_field_visibility loads and saves the selected preference through
        # PreferenceManager. Refresh this request's instance so the response does
        # not render the field button state from one click behind.
        preference.refresh_from_db(fields=["display_fields"])
    except (ValueError, ApplicationField.DoesNotExist) as e:
        return HttpResponse(f"Invalid field: {e}", status=400)

    return None


def _change_data_view_options(
    preference: UserListViewPreference,
    dataview_fields,
    post_data,
) -> HttpResponse | None:
    view_type = post_data["dataview_options_view_type"]
    if view_type != preference.view_type:
        return HttpResponse("Invalid options view type", status=400)

    definition = DATAVIEW_REGISTRY.get(view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    form_cls = definition.create_opts_form(dataview_fields)
    form = form_cls(post_data)
    if not form.is_valid():
        return HttpResponse("Invalid options", status=400)

    options = dict(preference.options or {})
    option_model = definition.get_options_model()
    try:
        options[view_type] = option_model.model_validate(form.cleaned_data).model_dump()
    except PydanticValidationError as error:
        return HttpResponse(f"Invalid options: {error}", status=400)

    preference.options = options
    preference.save(update_fields=["options"])
    return None


def _change_split_view(preference: UserListViewPreference, post_data) -> HttpResponse | None:
    preference.split_view_enabled = str(post_data["split_view_enabled"]).lower() == "true"
    preference.save(update_fields=["split_view_enabled"])
    return None


def _change_data_view_type(preference: UserListViewPreference, post_data) -> HttpResponse | None:
    view_type = post_data["view_type"]
    
    registered_view_type = DATAVIEW_REGISTRY.get(view_type)
    if registered_view_type is None or not registered_view_type.available_for_model(preference.content_type.model_class()):
        return HttpResponse("Invalid view type", status=400)

    preference.view_type = view_type
    preference.save(update_fields=["view_type"])
    return None


def _render_display_options(
    request: HttpRequest,
    content_type_id: int,
    preference: UserListViewPreference,
) -> HttpResponse:
    dataview_fields = get_data_view_fields(preference)
    return render(
        request,
        "cotton/features/dataviews/display_options.html",
        {
            "content_type_id": content_type_id,
            "view_types": [vt for vt in DATAVIEW_REGISTRY.values()],
            "preference": preference,
            "fields": dataview_fields,
            "accessible_fields": _get_accessible_application_fields(dataview_fields),
            "dataview_options_form": _get_dataview_options_form(
                preference,
                _get_accessible_application_fields(dataview_fields),
                request,
            ),
            "csrf_token": get_token(request),
        },
    )


def _get_preference_operation(post_data) -> str | None:
    if "view_type" in post_data:
        return "change_type"
    if "split_view_enabled" in post_data:
        return "split_view"
    if "dataview_options_view_type" in post_data:
        return "opt"
    if "toggle_field_id" in post_data:
        return "field"
    return None


@router.register(
    path="components/change_data_view_preference/<int:content_type_id>/",
    name="components_update_dataview_preference",
)
def update_dataview_preference(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Changes the dataview preference

    Args:
        request (HttpRequest): the request object
        content_type_id (int): The content type ID

    Returns:
        HttpResponse: the rendered datatable with the different preferences
    """
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    # Get the content type, user, and list view preference
    content_type = get_object_or_404(ContentType, id=content_type_id)
    user = request.user
    manager = PreferenceManager(user)
    preference = manager.get_or_create_selected(UserListViewPreference, {
        "content_type_id": content_type.id,
    })

    if not manager.can_manage(preference):
        return HttpResponse("Forbidden", status=403)

    operation = _get_preference_operation(request.POST)
    match operation:
        case "change_type":
            error_response = _change_data_view_type(preference, request.POST)
        case "split_view":
            error_response = _change_split_view(preference, request.POST)
        case "opt":
            dataview_fields = get_data_view_fields(preference)
            error_response = _change_data_view_options(
                preference,
                _get_accessible_application_fields(dataview_fields),
                request.POST,
            )
        case "field":
            error_response = _change_data_view_field_visibility(request, content_type, preference, request.POST)
        case _:
            error_response = None

    if error_response is not None:
        return error_response

    return _render_display_options(request, content_type_id, preference)
