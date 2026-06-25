from itertools import count
import json

from django.forms import modelform_factory
from django import forms
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.middleware.csrf import get_token
from bloomerp.components.application_fields.filters import filters_init
from bloomerp.models.definition import ObjectAction, get_model_config
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.utils.requests import render_message
from bloomerp.router import router
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import QueryDict
from django.contrib.contenttypes.models import ContentType
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.services.permission_services import create_permission_str
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.services.user_services import toggle_field_visibility
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.utils.filters import filter_model
from bloomerp.models.users.user_list_view_preference import UserListViewPreference, ViewTypeEnum
from bloomerp.models import ApplicationField
from django.db.models import Model, QuerySet
from dataclasses import dataclass
import uuid
from pydantic import ValidationError as PydanticValidationError
from bloomerp.dataviews.base import DataviewPagination
from bloomerp.dataviews.base import DataviewRenderState

from bloomerp.utils.stopwatch import Stopwatch

# -----------------------------------
# Filter helpers
# -----------------------------------
SHELL_RESERVED_QUERY_KEYS = {
    "q",
    "page",
    "_component_id",
}


@dataclass
class DataViewQueryState:
    content_type: ContentType
    model: type
    preference: UserListViewPreference
    dataview_options: object | None
    data_view_fields: object
    data_view_render_fields: list[ApplicationField]
    avatar_field: ApplicationField | None
    queryset: QuerySet
    query: str | None
    renderer_context: dict
    count: int = 0


def _build_data_view_query_state(request: HttpRequest, content_type_id: int) -> DataViewQueryState | HttpResponse:
    """Builds the dataview query state

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type id

    Returns:
        DataViewQueryState | HttpResponse: _description_
    """
    # Get the query
    query = request.GET.get('q')
    
    # Get the model and content type
    Model, content_type = get_model_and_content_type_or_404(content_type_id)

    # Get the permissions manager and initial queryset
    permission_manager = UserPermissionManager(request.user)
    queryset = permission_manager.get_queryset(Model, create_permission_str(Model, "view"))
    
    # Get preference and options
    preference = UserListViewPreference.get_or_create_for_user(request.user, content_type)
    dataview_options = _get_data_view_options(preference)
    data_view_fields = get_data_view_fields(preference)
    avatar_field, data_view_render_fields = _split_avatar_field(data_view_fields)

    # String search if 
    if query:
        queryset = string_search_on_queryset(queryset, query)

    definition = _get_data_view_type_definition(preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    reserved_query_keys = SHELL_RESERVED_QUERY_KEYS | definition.renderer_cls.get_reserved_query_params()
    filter_querydict = request.GET.copy()
    for key in reserved_query_keys:
        filter_querydict.pop(key, None)
    for key in list(filter_querydict.keys()):
        if key.startswith("_arg_"):
            filter_querydict.pop(key, None)
    filter_querydict = _apply_default_filters_to_querydict(
        filter_querydict,
        _normalize_default_filters(preference.default_filters or {}),
    )
    
    queryset = filter_model(Model, filter_querydict, queryset)
    
    queryset, renderer_context = definition.renderer_cls.apply_sorting(
        queryset,
        request,
        data_view_fields,
        dataview_options,
    )

    return DataViewQueryState(
        content_type=content_type,
        model=Model,
        preference=preference,
        dataview_options=dataview_options,
        data_view_fields=data_view_fields,
        data_view_render_fields=data_view_render_fields,
        avatar_field=avatar_field,
        queryset=queryset,
        query=query,
        renderer_context=renderer_context,
        count=queryset.count()
    )


def _split_avatar_field(data_view_fields) -> tuple[ApplicationField | None, list[ApplicationField]]:
    avatar_field = None
    fields = []

    for field in data_view_fields.visible_fields:
        if field.field == "avatar":
            avatar_field = field
            continue
        fields.append(field)

    return avatar_field, fields


def _get_accessible_application_fields(data_view_fields) -> list[ApplicationField]:
    return [field for field, _is_visible in data_view_fields.accessible_fields]


def _get_component_args(request:HttpRequest) -> dict[str, str]:
    """Returns the component args

    Args:
        request (HttpRequest): the request object

    Returns:
        dict[str, str]: the parsed arguments
    """
    args = {}
    for arg, value in request.GET.items():
        if arg.startswith("_arg_"):
            cleaned_arg = arg[5:].lower().replace("_","-")
            args[cleaned_arg] = value
    
    return args


def _get_actions(model:type[Model]) -> list[ObjectAction]:
    config = get_model_config(model)
    if config:
        return config.object_actions
    return []


def _get_data_view_type_definition(view_type: str):
    try:
        return ViewTypeEnum.from_key(view_type)
    except ValueError:
        return None


def _normalize_default_filters(raw_filters) -> dict[str, str | list[str]]:
    if not isinstance(raw_filters, dict):
        return {}

    normalized = {}
    for raw_key, raw_value in raw_filters.items():
        key = str(raw_key)
        if not key or key in SHELL_RESERVED_QUERY_KEYS or key.startswith("_arg_"):
            continue

        if isinstance(raw_value, list):
            values = [
                str(value)
                for value in raw_value
                if value is not None and str(value) != ""
            ]
            if values:
                normalized[key] = values
            continue

        if raw_value is None or str(raw_value) == "":
            continue

        normalized[key] = str(raw_value)

    return normalized


def _apply_default_filters_to_querydict(
    querydict: QueryDict,
    default_filters: dict[str, str | list[str]],
) -> QueryDict:
    merged = querydict.copy()

    for key, value in default_filters.items():
        merged.pop(key, None)
        if isinstance(value, list):
            merged.setlist(key, value)
        else:
            merged[key] = value

    return merged


def _get_data_view_options_initial(preference: UserListViewPreference, view_type: str) -> dict:
    definition = _get_data_view_type_definition(view_type)
    if definition is None:
        return {}

    dataview_options = _get_data_view_options(preference, view_type)
    if dataview_options is None:
        return {}
    return dataview_options.model_dump()


def _get_data_view_options(preference: UserListViewPreference, view_type: str | None = None):
    """Returns the data view options for a specific preference type
    """
    view_type = view_type or preference.view_type
    definition = _get_data_view_type_definition(view_type)
    if definition is None:
        return None

    raw_options = (preference.options or {}).get(view_type, {})
    options_model = definition.get_options_model()
    try:
        return options_model.model_validate(raw_options or {})
    except PydanticValidationError:
        return options_model.model_validate({})


def _get_data_view_options_form(
    preference: UserListViewPreference,
    accessible_fields: list[ApplicationField],
    request: HttpRequest,
) -> forms.Form | None:
    definition = _get_data_view_type_definition(preference.view_type)
    if definition is None or not definition.opts:
        return None

    form_cls = definition.create_opts_form(accessible_fields)
    return form_cls(initial=_get_data_view_options_initial(preference, definition.key))


def _render_display_options(
    request: HttpRequest,
    content_type_id: int,
    preference: UserListViewPreference,
) -> HttpResponse:
    data_view_fields = get_data_view_fields(preference)
    return render(
        request,
        "cotton/features/dataviews/display_options.html",
        {
            "content_type_id": content_type_id,
            "view_types": [vt.value for vt in ViewTypeEnum],
            "preference": preference,
            "fields": data_view_fields,
            "accessible_fields": _get_accessible_application_fields(data_view_fields),
            "dataview_options_form": _get_data_view_options_form(
                preference,
                _get_accessible_application_fields(data_view_fields),
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
    if "default_filters" in post_data:
        return "default_filters"
    return None


def _change_default_filters(preference: UserListViewPreference, post_data) -> HttpResponse | None:
    try:
        payload = json.loads(post_data.get("default_filters") or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid default filters", status=400)

    preference.default_filters = _normalize_default_filters(payload)
    preference.save(update_fields=["default_filters"])
    return None


def _change_data_view_type(preference: UserListViewPreference, post_data) -> HttpResponse | None:
    view_type = post_data["view_type"]
    if _get_data_view_type_definition(view_type) is None:
        return HttpResponse("Invalid view type", status=400)

    preference.view_type = view_type
    preference.save(update_fields=["view_type"])
    return None


def _change_split_view(preference: UserListViewPreference, post_data) -> HttpResponse | None:
    preference.split_view_enabled = str(post_data["split_view_enabled"]).lower() == "true"
    preference.save(update_fields=["split_view_enabled"])
    return None


def _change_data_view_options(
    preference: UserListViewPreference,
    data_view_fields,
    post_data,
) -> HttpResponse | None:
    view_type = post_data["dataview_options_view_type"]
    if view_type != preference.view_type:
        return HttpResponse("Invalid options view type", status=400)

    definition = _get_data_view_type_definition(view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    form_cls = definition.create_opts_form(data_view_fields)
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


def _change_data_view_field_visibility(
    request: HttpRequest,
    content_type: ContentType,
    preference: UserListViewPreference,
    post_data,
) -> HttpResponse | None:
    try:
        field_id = int(post_data["toggle_field_id"])
        view_type = post_data.get("toggle_view_type", preference.view_type)
        if _get_data_view_type_definition(view_type) is None:
            return HttpResponse("Invalid view type", status=400)

        permission_manager = UserPermissionManager(request.user)
        application_field = ApplicationField.objects.get(id=field_id)

        if not permission_manager.has_field_permission(
            application_field,
            create_permission_str(content_type.model_class(), "view")
        ):
            return HttpResponse("Permission denied", status=403)

        toggle_field_visibility(request.user, content_type, field_id, view_type)
    except (ValueError, ApplicationField.DoesNotExist) as e:
        return HttpResponse(f"Invalid field: {e}", status=400)

    return None


def _render_data_view_body(
    request: HttpRequest,
    state: DataViewQueryState,
    pagination: DataviewPagination,
    context: dict,
) -> str:
    definition = _get_data_view_type_definition(state.preference.view_type)
    if definition is None:
        return ""

    render_state = DataviewRenderState(
        request=request,
        content_type_id=state.content_type.id,
        content_type=state.content_type,
        model=state.model,
        preference=state.preference,
        queryset=state.queryset,
        fields=state.data_view_fields,
        render_fields=state.data_view_render_fields,
        avatar_field=state.avatar_field,
        options=state.dataview_options,
        object_actions=context.get("object_actions", []),
        extra_context=context,
    )
    return definition.renderer_cls(render_state).render(pagination)
    

# -----------------------------------
# Components
# -----------------------------------
@router.register(
    path="components/data_view/<int:content_type_id>/",
    name="components_data_view",
)
def data_view(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """
    Renders the data table component. A data table is a table that takes in a content type 
    id and renders a table of the corresponding model's data.
    It supports the following features:
    - filtering
    - permissions management
    - string searching
    """
    state = _build_data_view_query_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state
    
    definition = _get_data_view_type_definition(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    pagination = definition.renderer_cls.paginate_queryset(
        state.queryset,
        state.preference,
        request,
        state.dataview_options,
    )
    
    page_querystring = request.GET.copy()
    page_querystring.pop('page', None)
    search_querystring = request.GET.copy()
    search_querystring.pop('page', None)
    search_querystring.pop('q', None)
    create_querystring = request.GET.copy()
    create_querystring.pop('page', None)
    create_querystring.pop('q', None)
    export_querystring = request.GET.copy()
    export_querystring.pop('page', None)
    export_querystring.pop('_component_id', None)
    for key in definition.renderer_cls.get_reserved_query_params():
        search_querystring.pop(key, None)
        create_querystring.pop(key, None)
        export_querystring.pop(key, None)
    sync_url = request.headers.get("X-Bloomerp-Sync-Url", "false").lower() == "true"
    component_id = request.GET.get('_component_id')

    data_view_base_url = reverse(
        "components_data_view",
        kwargs={"content_type_id": content_type_id},
    )
    data_view_querystring = request.GET.urlencode()
    data_view_url = (
        f"{data_view_base_url}?{data_view_querystring}"
        if data_view_querystring
        else data_view_base_url
    )

    context = {
        'content_type_id': content_type_id,
        'queryset': pagination.queryset,
        'page_obj': pagination.page_obj,
        'fields': state.data_view_fields,
        'data_view_render_fields': state.data_view_render_fields,
        'avatar_field': state.avatar_field,
        'preference': state.preference,
        'render_id': str(uuid.uuid4()),
        'search_query': state.query or '',
        'search_querystring': search_querystring.urlencode(),
        'create_querystring': create_querystring.urlencode(),
        'export_querystring': export_querystring.urlencode(),
        'sync_url': sync_url,
        'filter_section' : filters_init(request, content_type_id).content.decode("utf-8"), # TODO: optimize because of multiple queries
        'page_querystring': page_querystring.urlencode(),
        'pagination_pages': pagination.pagination_pages or [],
        'show_global_pagination': pagination.show_global_pagination,
        'component_id': component_id,
        'component_args' : _get_component_args(request),
        'object_actions' : _get_actions(state.queryset.model),
        'view_types' : [vt.value for vt in ViewTypeEnum],
        'dataview_options_form': _get_data_view_options_form(
            state.preference,
            _get_accessible_application_fields(state.data_view_fields),
            request,
        ),
        'data_view_base_url': data_view_base_url,
        'data_view_url': data_view_url,
        'default_filters_json': json.dumps(
            _normalize_default_filters(state.preference.default_filters or {})
        ),
        'count' : state.count,
    }
    context.update(state.renderer_context)
    context["rendered_dataview"] = _render_data_view_body(request, state, pagination, context)
    
    return render(request, 'components/objects/dataview.html', context)


@router.register(
    path="components/data_view/<int:content_type_id>/action/<str:action>/",
    name="components_data_view_action",
)
def data_view_action(request: HttpRequest, content_type_id: int, action: str) -> HttpResponse:
    """Dispatches a view-specific dataview action to the active renderer."""
    state = _build_data_view_query_state(request, content_type_id)
    if isinstance(state, HttpResponse):
        return state

    definition = _get_data_view_type_definition(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    return definition.renderer_cls.handle_action(action, request, state)
    

@router.register(
    path="components/change_data_view_preference/<int:content_type_id>/",
    name="components_change_data_view_preference",
)
def change_data_view_preference(request: HttpRequest, content_type_id: int) -> HttpResponse:
    """Changes the datatable preference

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
    preference = UserListViewPreference.get_or_create_for_user(
        user=user,
        content_type_or_model=content_type,
    )
    operation = _get_preference_operation(request.POST)
    match operation:
        case "change_type":
            error_response = _change_data_view_type(preference, request.POST)
        case "split_view":
            error_response = _change_split_view(preference, request.POST)
        case "opt":
            data_view_fields = get_data_view_fields(preference)
            error_response = _change_data_view_options(
                preference,
                _get_accessible_application_fields(data_view_fields),
                request.POST,
            )
        case "field":
            error_response = _change_data_view_field_visibility(request, content_type, preference, request.POST)
        case "default_filters":
            error_response = _change_default_filters(preference, request.POST)
        case _:
            error_response = None

    if error_response is not None:
        return error_response
    
    return _render_display_options(request, content_type_id, preference)


    
    
