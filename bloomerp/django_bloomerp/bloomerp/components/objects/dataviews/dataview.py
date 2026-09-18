import json

from django import forms
from django.core import signing
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.core.exceptions import FieldDoesNotExist
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.filters.parser import parse_filters
from bloomerp.models.definition import (
    DataviewAction,
    DataviewActionContext,
    DataviewHTMLAction,
    DataviewModalAction,
    ObjectAction,
    get_default_dataview_actions,
    get_model_config,
)
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.router import router
from django.http import HttpRequest
from django.http import HttpResponse
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models import ApplicationField
from django.db.models import Model, QuerySet
import uuid
from pydantic import ValidationError as PydanticValidationError
from bloomerp.dataviews.definition import (
    DataviewPagination,
    DataviewState,
    DataviewTypeDefinition,
)

# -----------------------------------
# Filter helpers
# -----------------------------------
SHELL_RESERVED_QUERY_KEYS = {
    "q",
    "page",
    "_component_id",
    "_dataview_operation_context",
}

DATAVIEW_OPERATION_CONTEXT_PARAM = "_dataview_operation_context"
DATAVIEW_OPERATION_CONTEXT_SALT = "bloomerp.dataview.renderer-operation"
DATAVIEW_OPERATION_CONTEXT_MAX_AGE = 60 * 60 * 24


def _sign_dataview_operation_context(
    request: HttpRequest,
    preference: UserListViewPreference,
) -> str | None:
    """Authorize this user to reuse an explicitly embedded preference."""
    if not request.user.is_authenticated or request.user.pk is None:
        return None

    return signing.dumps(
        {
            "user_id": str(request.user.pk),
            "content_type_id": preference.content_type_id,
            "preference_id": preference.pk,
        },
        salt=DATAVIEW_OPERATION_CONTEXT_SALT,
        compress=True,
    )


def _valid_dataview_operation_context(
    request: HttpRequest,
    *,
    content_type_id: int,
    preference_id: int,
) -> bool:
    """Validate the signed fallback for a server-authorized embedding."""
    token = request.GET.get(DATAVIEW_OPERATION_CONTEXT_PARAM)
    if not token or not request.user.is_authenticated or request.user.pk is None:
        return False

    try:
        payload = signing.loads(
            token,
            salt=DATAVIEW_OPERATION_CONTEXT_SALT,
            max_age=DATAVIEW_OPERATION_CONTEXT_MAX_AGE,
        )
    except (signing.BadSignature, signing.SignatureExpired):
        return False

    return payload == {
        "user_id": str(request.user.pk),
        "content_type_id": content_type_id,
        "preference_id": preference_id,
    }


def _build_dataview_state(
    request: HttpRequest,
    content_type_id: int,
    preference: UserListViewPreference | None = None,
    *,
    base_queryset: QuerySet | None = None,
    additional_reserved_query_keys: set[str] | None = None,
) -> DataviewState | HttpResponse:
    """Builds the dataview query state

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type id
        preference: An explicit available preference, or the user's selected preference.

    Returns:
        DataviewState | HttpResponse: The prepared state or an error response.
    """
    # Get the query
    query = request.GET.get('q')
    
    # Get the model and content type
    Model, content_type = get_model_and_content_type_or_404(content_type_id)

    # Use an explicitly scoped queryset when embedding a data view. Otherwise,
    # apply the user's standard row-level view permissions.
    manager = UserPolicyManager(request.user)
    
    queryset = (
        base_queryset
        if base_queryset is not None
        else manager.get_queryset(
            Model,
            BloomerpPermission.VIEW,
        )
    )
    
    # Get preference and options
    if preference is None:
        preference = PreferenceManager(request.user).get_or_create_selected(
            UserListViewPreference,
            {"content_type_id": content_type.id},
        )
    elif preference.content_type_id != content_type.id:
        return HttpResponse("Invalid list view preference", status=400)
    dataview_options = _get_dataview_options(preference)
    dataview_fields = get_data_view_fields(preference, user=request.user)
    avatar_field, dataview_render_fields = _split_avatar_field(dataview_fields)

    # String search if 
    if query:
        queryset = string_search_on_queryset(queryset, query)

    definition = DATAVIEW_REGISTRY.get(preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    reserved_query_keys = (
        SHELL_RESERVED_QUERY_KEYS
        | definition.renderer_cls.get_reserved_query_params()
        | (additional_reserved_query_keys or set())
    )
    filter_querydict = request.GET.copy()
    for key in reserved_query_keys:
        filter_querydict.pop(key, None)
    for key in list(filter_querydict.keys()):
        if key.startswith("_arg_"):
            filter_querydict.pop(key, None)
    filter_querydict = preference.apply_default_filters(filter_querydict)
    
    filters = parse_filters(filter_querydict, model=Model)
    
    manager.validate_filters(Model, filters)
    
    filter_manager = ModelFilterManager(Model)
    queryset = filter_manager.apply(
        filters,
        queryset
    )
    
    queryset = _select_related_rendered_relations(
        queryset,
        dataview_render_fields + ([avatar_field] if avatar_field else []),
    )
    
    queryset, renderer_context = definition.renderer_cls.apply_sorting(
        queryset,
        request,
        dataview_fields,
        dataview_options,
    )

    count = queryset.count()
    queryset = manager.annotate_field_permissions(
        queryset,
        dataview_render_fields + ([avatar_field] if avatar_field else []),
        BloomerpPermission.VIEW,
    )

    return DataviewState(
        request=request,
        content_type=content_type,
        model=Model,
        preference=preference,
        options=dataview_options,
        fields=dataview_fields,
        render_fields=dataview_render_fields,
        avatar_field=avatar_field,
        queryset=queryset,
        query=query,
        context=renderer_context,
        count=count,
        filters=filters
    )


def _split_avatar_field(dataview_fields) -> tuple[ApplicationField | None, list[ApplicationField]]:
    avatar_field = None
    fields = []

    for field in dataview_fields.visible_fields:
        if field.field == "avatar":
            avatar_field = field
            continue
        fields.append(field)

    return avatar_field, fields


def _select_related_rendered_relations(
    queryset: QuerySet,
    application_fields: list[ApplicationField],
) -> QuerySet:
    """Eager-load direct relations required to render the current DataView page."""
    relation_names = []
    for application_field in application_fields:
        try:
            model_field = queryset.model._meta.get_field(application_field.field)
        except FieldDoesNotExist:
            continue

        if (
            getattr(model_field, "concrete", False)
            and (model_field.many_to_one or model_field.one_to_one)
        ):
            relation_names.append(model_field.name)

    if not relation_names:
        return queryset

    return queryset.select_related(*dict.fromkeys(relation_names))


def _get_accessible_application_fields(dataview_fields) -> list[ApplicationField]:
    return [field for field, _is_visible in dataview_fields.accessible_fields]


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


def _get_dataview_options_initial(preference: UserListViewPreference, view_type: str) -> dict:
    definition = DATAVIEW_REGISTRY.get(view_type)
    if definition is None:
        return {}

    dataview_options = _get_dataview_options(preference, view_type)
    if dataview_options is None:
        return {}
    return dataview_options.dump_options()


def _get_dataview_options(preference: UserListViewPreference, view_type: str | None = None):
    """Returns the data view options for a specific preference type
    """
    view_type = view_type or preference.view_type
    definition = DATAVIEW_REGISTRY.get(view_type)
    if definition is None:
        return None

    raw_options = (preference.options or {}).get(view_type, {})
    options_model = definition.config_cls
    try:
        return options_model.model_validate(raw_options or {})
    except PydanticValidationError:
        try:
            return options_model.model_validate({})
        except PydanticValidationError:
            # Some views require configuration before they can produce an
            # options model. Keep the state unconfigured so its form can be
            # rendered and collect those required values.
            return None


def _get_dataview_options_form(
    state: DataviewState,
) -> forms.Form | None:
    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None or not definition.config_cls.option_field_names():
        return None

    form_cls = definition.config_cls.form_factory(state)
    return form_cls(
        initial=_get_dataview_options_initial(state.preference, definition.key)
    )


def _render_dataview_body(
    state: DataviewState,
    pagination: DataviewPagination,
    context: dict,
) -> str:
    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None:
        return ""

    state.object_actions = context.get("object_actions", [])
    state.context = context
    return definition.renderer_cls(state).render(pagination)


def _get_configured_dataview_actions(
    model: type[Model],
) -> list[DataviewAction | DataviewHTMLAction | DataviewModalAction]:
    config = get_model_config(model)
    if config and config.model_view_settings:
        return config.model_view_settings.dataview_actions
    return get_default_dataview_actions()


def _build_dataview_action_context(
    request: HttpRequest,
    state: DataviewState,
) -> DataviewActionContext:
    return DataviewActionContext(
        request=request,
        model=state.model,
        content_type=state.content_type,
        preference=state.preference,
        queryset=state.queryset,
        querystring=request.GET.urlencode(),
    )


def _render_dataview_actions(
    request: HttpRequest,
    state: DataviewState,
    context: dict,
    action_ids: list[str] | None = None,
) -> list[str]:
    action_context = _build_dataview_action_context(request, state)
    rendered_actions: list[str] = []
    allowed_action_ids = set(action_ids) if action_ids is not None else None

    for action in _get_configured_dataview_actions(state.model):
        if allowed_action_ids is not None and action.id not in allowed_action_ids:
            continue

        try:
            should_render = action.should_render_func(action_context)
        except Exception:
            should_render = False
        if not should_render:
            continue

        action_template_context = {
            **context,
            "action": action,
            "action_context": action_context,
            "model": state.model,
        }
        if isinstance(action, DataviewHTMLAction):
            template_name = action.template_name
        elif isinstance(action, DataviewModalAction):
            template_name = "components/objects/dataview_actions/modal_action.html"
            action_template_context["endpoint"] = action.endpoint(action_context)
        else:
            template_name = "components/objects/dataview_actions/action.html"
            execution_url = reverse(
                "components_dataview_action",
                kwargs={
                    "content_type_id": state.content_type.pk,
                    "action_id": action.id,
                },
            )
            if action_context.querystring:
                execution_url = f"{execution_url}?{action_context.querystring}"
            action_template_context["execution_url"] = execution_url

        rendered_actions.append(
            render_to_string(
                template_name,
                action_template_context,
                request=request,
            )
        )

    return rendered_actions
    

# -----------------------------------
# Components
# -----------------------------------
@router.register(
    path="components/dataview/<int:content_type_id>/",
    name="components_dataview",
)
def dataview(
    request: HttpRequest,
    content_type_id: int,
    preference: UserListViewPreference | None = None,
    *,
    base_queryset: QuerySet | None = None,
    additional_reserved_query_keys: set[str] | None = None,
    component_id: str | None = None,
    component_args: dict[str, str] | None = None,
    dataview_base_url: str | None = None,
    before_data_view: str = "",
    actions: list[str] | None = None,
) -> HttpResponse:
    """Renders a dataview, applied with permission.

    A dataview can be of type:
        - table
        - kanban
        - card
        - ...

    Args:
        request (HttpRequest): request object
        content_type_id (int): content type id
        preference (UserListViewPreference | None, optional): Injected preference object. Defaults to None.
        base_queryset (QuerySet | None, optional): Optional base queryset. Defaults to None.
        additional_reserved_query_keys (set[str] | None, optional): Additional reserved query keys. Defaults to None.
        component_id (str | None, optional): The id of the frontend component. Defaults to None.
        component_args (dict[str, str] | None, optional): Optional frontend component arguments. Defaults to None.
        dataview_base_url (str | None, optional): The base URL of the dataview. Defaults to None.
        before_data_view (str, optional): Optional HTML snippet that would render before. Defaults to "".
        actions (list[str] | None, optional): IDs of the actions to render. When
            omitted, all actions configured for the model are rendered.

    Returns:
        HttpResponse: The response
    """
    
    preference_was_explicit = preference is not None
    state = _build_dataview_state(
        request,
        content_type_id,
        preference,
        base_queryset=base_queryset,
        additional_reserved_query_keys=additional_reserved_query_keys,
    )
    if isinstance(state, HttpResponse):
        return state

    if preference_was_explicit:
        state.operation_context_token = _sign_dataview_operation_context(
            request,
            state.preference,
        )
    
    
    
    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    pagination = definition.renderer_cls.paginate_queryset(
        state.queryset,
        state.preference,
        request,
        state.options,
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
    sync_url = (
        request.headers.get("X-Bloomerp-Sync-Url", "false").lower() == "true"
        or definition.key == "file_browser"
    )
    component_id = component_id or request.GET.get('_component_id')

    dataview_base_url = dataview_base_url or reverse(
        "components_dataview",
        kwargs={"content_type_id": content_type_id},
    )
    data_view_querystring = request.GET.urlencode()
    renderer_operation_querydict = request.GET.copy()
    if state.operation_context_token:
        renderer_operation_querydict[DATAVIEW_OPERATION_CONTEXT_PARAM] = (
            state.operation_context_token
        )
    renderer_operation_querystring = renderer_operation_querydict.urlencode()
    data_view_url = (
        f"{dataview_base_url}?{data_view_querystring}"
        if data_view_querystring
        else dataview_base_url
    )
    htmx_target = (
        getattr(getattr(request, "htmx", None), "target", None)
        or request.headers.get("HX-Target", "")
    )
    is_data_section_request = str(htmx_target).lstrip("#") == "data-view-data-section"

    context = {
        'content_type_id': content_type_id,
        'queryset': pagination.queryset,
        'page_obj': pagination.page_obj,
        'fields': state.fields,
        'dataview_render_fields': state.render_fields,
        'avatar_field': state.avatar_field,
        'preference': state.preference,
        'render_id': str(uuid.uuid4()),
        'search_query': state.query or '',
        'search_querystring': search_querystring.urlencode(),
        'create_querystring': create_querystring.urlencode(),
        'export_querystring': export_querystring.urlencode(),
        'sync_url': sync_url,
        'page_querystring': page_querystring.urlencode(),
        'pagination_pages': pagination.pagination_pages or [],
        'show_global_pagination': pagination.show_global_pagination,
        'component_id': component_id,
        'component_args' : {**_get_component_args(request), **(component_args or {})},
        'object_actions' : _get_actions(state.queryset.model),
        'view_types' : [vt for vt in DATAVIEW_REGISTRY.values() if vt.available_for_model(state.model)],
        'dataview_options_form': _get_dataview_options_form(
            state,
        ),
        'dataview_base_url': dataview_base_url,
        'data_view_url': data_view_url,
        'renderer_operation_querystring': renderer_operation_querystring,
        'initial_filters': request.GET.get('filter'),
        'count' : state.count,
        'before_data_view': before_data_view,
        'is_data_section_request': is_data_section_request,
        'filters' : state.filters
    }
    context.update(state.context)
    context["rendered_dataview_actions"] = _render_dataview_actions(
        request,
        state,
        context,
        actions,
    )
    context["rendered_dataview"] = _render_dataview_body(state, pagination, context)

    return render(request, 'components/objects/dataview.html', context)
