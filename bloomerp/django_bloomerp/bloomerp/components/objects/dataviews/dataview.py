from django.forms import modelform_factory
from django import forms
from django.shortcuts import get_object_or_404, render
from bloomerp.components.application_fields.filters import filters_init
from bloomerp.models.definition import ObjectAction, get_model_config
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.utils.requests import render_message
from bloomerp.router import router
from django.http import HttpResponse
from django.http import HttpRequest
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

# TODO: Refactor and get rid of this code
LOOKUP_LABELS = {
    "exact": "is",
    "equals": "is",
    "icontains": "contains",
    "contains": "contains",
    "startswith": "starts with",
    "endswith": "ends with",
    "gte": "≥",
    "lte": "≤",
    "gt": ">",
    "lt": "<",
    "isnull": "is empty",
    "in": "in",
    "year": "year is",
    "month": "month is",
    "day": "day is",
    "week": "week is",
    "today": "is today",
    "yesterday": "was yesterday",
    "this_week": "is in this week",
    "last_week": "is in last week",
    "this_month": "is in this month",
    "last_month": "is in last month",
    "this_quarter": "is in this quarter",
    "last_quarter": "is in last quarter",
    "this_year": "is in this year",
    "last_year": "is in last year",
}


def _humanize_field_path(value: str) -> str:
    parts = [part for part in value.split("__") if part]
    labels = [part.replace("_", " ").title() for part in parts]
    return " \u2192 ".join(labels)


def _format_applied_filters(query_params, reserved_keys: set[str] | None = None) -> list[dict]:
    # TODO: formatting function is also implemented in the frontend, we should unify this logic by moving this to the frontend
    # we can do so by just creating a component which onload formats the applied filters or something like that
    applied = []

    reserved_keys = reserved_keys or SHELL_RESERVED_QUERY_KEYS

    for key in query_params.keys():
        if key in reserved_keys or key.startswith("_arg_"):
            continue

        values = query_params.getlist(key)
        if not values:
            continue

        raw_value = ", ".join([str(v) for v in values if v != ""])
        if raw_value == "":
            continue

        parts = [part for part in key.split("__") if part]
        lookup = None
        field_path = key
        if len(parts) > 1 and parts[-1] in LOOKUP_LABELS:
            lookup = parts[-1]
            field_path = "__".join(parts[:-1])

        field_label = _humanize_field_path(field_path)
        lookup_label = LOOKUP_LABELS.get(lookup, lookup or "is")

        if lookup == "isnull":
            lowered = raw_value.lower()
            if lowered in {"true", "1", "yes"}:
                label = f"{field_label} is empty"
            else:
                label = f"{field_label} has value"
        elif lookup in {"today", "yesterday", "this_week", "last_week", "this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year"}:
            label = f"{field_label} {lookup_label}"
        else:
            label = f"{field_label} {lookup_label} {raw_value}"

        applied.append({
            "key": key,
            "label": label,
            "tooltip": f"{key} = {raw_value}",
        })

    return applied

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


def _get_preference_operation(post_data) -> str | None:
    if "view_type" in post_data:
        return "change_type"
    if "dataview_options_view_type" in post_data:
        return "opt"
    if "toggle_field_id" in post_data:
        return "field"
    return None


def _change_data_view_type(preference: UserListViewPreference, post_data) -> HttpResponse | None:
    view_type = post_data["view_type"]
    if _get_data_view_type_definition(view_type) is None:
        return HttpResponse("Invalid view type", status=400)

    preference.view_type = view_type
    preference.save(update_fields=["view_type"])
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
        'applied_filters': _format_applied_filters(
            request.GET,
            SHELL_RESERVED_QUERY_KEYS | definition.renderer_cls.get_reserved_query_params(),
        ),
        'component_id': component_id,
        'component_args' : _get_component_args(request),
        'object_actions' : _get_actions(state.queryset.model),
        'view_types' : [vt.value for vt in ViewTypeEnum],
        'dataview_options_form': _get_data_view_options_form(
            state.preference,
            _get_accessible_application_fields(state.data_view_fields),
            request,
        ),
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
        case "opt":
            data_view_fields = get_data_view_fields(preference)
            error_response = _change_data_view_options(
                preference,
                _get_accessible_application_fields(data_view_fields),
                request.POST,
            )
        case "field":
            error_response = _change_data_view_field_visibility(request, content_type, preference, request.POST)
        case _:
            error_response = None

    if error_response is not None:
        return error_response
    
    return data_view(request, content_type_id)


@router.register(
    path="components/dataview_edit_field/<int:application_field_id>/<str:object_id>/",
    name="components_dataview_edit_field",
)
def dataview_edit_field(request: HttpRequest, application_field_id:int, object_id: str) -> HttpResponse:
    """Renders the inline edit component for a dataview field.

    Args:
        request (HttpRequest): The request object.
        application_field_id (int): The application field ID to edit.

    Returns:
        HttpResponse: The rendered inline edit component.
    """
    # Retrieve the objects
    application_field = get_object_or_404(ApplicationField, id=application_field_id)
    model = application_field.get_model()
    object = get_object_or_404(application_field.get_model(), id=object_id)
    permission_str = f"change_{model._meta.model_name}"
    
    manager = UserPermissionManager(request.user)
    if not manager.has_access_to_object(object, permission_str):
        return HttpResponse(status=405)
    
    if not manager.has_field_permission(application_field, permission_str):
        return HttpResponse(status=405)
    
    if request.method == "GET":
        widget = application_field.get_widget()
        widget_choices = getattr(widget, "get_choices", lambda *_args, **_kwargs: [])()
        input_class = "select select-sm w-full bg-transparent border-0" if isinstance(widget, forms.Select) or widget_choices else "border-0 w-full bg-transparent input-sm"
        
        return HttpResponse(
            widget.render(
                name=application_field.field,
                value=getattr(object, application_field.field),
                attrs={
                    "class" : input_class,
                }
        ))
    elif request.method == "POST":
        FormCls = modelform_factory(
            model,
            fields=[application_field.field],
        )
        form = FormCls(request.POST, instance=object)
        if form.is_valid():
            form.save()
            return render_message(request, "Field updated successfully", "success")
        else:
            pass
            

    

    
    
