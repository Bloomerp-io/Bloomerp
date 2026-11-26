import uuid
from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import ForeignKey, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView
from pydantic import ValidationError as PydanticValidationError

from bloomerp.dataviews.definition import (
    DATAVIEW_PAGE_PARAM,
    BaseDataview,
    DataviewPagination,
    DataviewState,
)
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.filters.parser import parse_filters
from bloomerp.models import ApplicationField
from bloomerp.models.actions.dataview.add import can_create_dataview_object
from bloomerp.models.actions.dataview.builtins import get_dataview_actions
from bloomerp.models.actions.object.resolution import (
    get_object_actions,
    iter_object_actions,
)
from bloomerp.models.definition import (
    DataviewActionContext,
    DataviewHTMLAction,
    ObjectHTMLAction,
    get_model_config,
)
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.action_services import (
    ACTION_DATAVIEW_PREFERENCE_PARAM,
    render_action,
    with_dataview_context,
)
from bloomerp.services.object_contact_services import (
    get_object_contact_access,
    object_contact_context,
)
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.search_services import string_search_on_queryset
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.tokens import (
    REQUEST_TOKEN_QUERY_KEYS,
    DataviewToken,
    RequestToken,
    get_token,
    issue_token,
    request_query_params,
    request_token_headers,
    request_token_id,
)
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.views.mixins.htmx_mixin import HtmxMixin

# -----------------------------------
# Filter helpers
# -----------------------------------
SHELL_RESERVED_QUERY_KEYS = REQUEST_TOKEN_QUERY_KEYS | {
    "q",
    "selected_ids",
    "page",
    "_component_id",
    DATAVIEW_PAGE_PARAM,
    ACTION_DATAVIEW_PREFERENCE_PARAM,
}

class _DataviewPage(HtmxMixin, TemplateView):
    """Give a standalone Data View the standard Bloomerp page chrome."""

    template_name = "components/objects/dataview.html"

    def get_context_data(self, *, model_label: str, **kwargs: Any) -> dict[str, Any]:
        """Use the displayed model's name in the page breadcrumb."""
        context = super().get_context_data(**kwargs)
        context["route_title"] = model_label
        context["breadcrumbs"][-1]["text"] = model_label
        return context


def resolve_dataview_preference(
    request: HttpRequest,
    content_type_id: int,
    preference_id: int,
) -> UserListViewPreference:
    """Resolve a preference available to the viewer or authorized by a trusted embedding."""
    available = (
        PreferenceManager(request.user).get_available(
            UserListViewPreference, {"content_type_id": content_type_id},
        )
        .filter(Q(pk=preference_id) | Q(source_object_id=preference_id))
        .first()
    )
    if available is not None:
        return available.effective_preference
    layout_token = get_context_dataview_token(request, content_type_id)
    context = get_token(request)
    if (
        layout_token is not None and layout_token.preference_id == preference_id
        or context is not None and context.operation_preferences.get(content_type_id) == preference_id
    ):
        return get_object_or_404(
            UserListViewPreference, pk=preference_id, content_type_id=content_type_id,
        )
    raise Http404("Dataview preference not found")


def get_context_dataview_token(request: HttpRequest, content_type_id: int) -> DataviewToken | None:
    """Resolve this model's layout grant from the active request context."""
    context = get_token(request)
    if context is None:
        return None
    model, _content_type = get_model_and_content_type_or_404(content_type_id)
    return context.dataviews.get(model)


def build_execution_dataview_state(
    request: HttpRequest,
    content_type_id: int,
) -> DataviewState | HttpResponse:
    """Rebuild the originating dataview and its permissions for an action request."""
    preference = None
    raw_id = request.GET.get(ACTION_DATAVIEW_PREFERENCE_PARAM)
    if raw_id is not None and get_context_dataview_token(request, content_type_id) is None:
        try:
            preference_id = int(raw_id)
        except ValueError as error:
            raise Http404("Invalid dataview preference") from error
        preference = resolve_dataview_preference(request, content_type_id, preference_id)
    return _build_dataview_state(request, content_type_id, preference, calculate_count=False)


def _scope_related_dataview(
    request: HttpRequest, queryset: QuerySet, manager: UserPolicyManager, field_name: str,
) -> QuerySet:
    """Bind a signed related table to a parent record the viewer can access."""
    field = queryset.model._meta.get_field(field_name)
    parent_pk = request.GET.get("_arg_related_record")
    if not isinstance(field, ForeignKey) or not parent_pk:
        raise Http404
    try:
        parent = get_object_or_404(manager.get_queryset(field.related_model, BloomerpPermission.VIEW), pk=parent_pk)
    except ValidationError as error:
        raise Http404 from error
    if not manager.has_access_to_object(parent, BloomerpPermission.VIEW, fields=[field.remote_field.name]):
        raise Http404
    return queryset.filter(**{field.name: parent})


def _build_dataview_state(
    request: HttpRequest,
    content_type_id: int,
    preference: UserListViewPreference | None = None,
    *,
    calculate_count: bool = True,
    renderer_action: str | None = None,
) -> DataviewState | HttpResponse:
    """Builds the dataview query state

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type id
        preference: An explicit available preference, or the user's selected preference.
        calculate_count: Calculate the filtered total when the renderer needs it.
        renderer_action: Let the selected renderer decide whether its operation needs a total.

    Returns:
        DataviewState | HttpResponse: The prepared state or an error response.
    """
    # Get the query
    query = request.GET.get('q')
    
    # Get the model and content type
    Model, content_type = get_model_and_content_type_or_404(content_type_id)

    context_token = get_token(request)
    token = context_token.dataviews.get(Model) if context_token else None
    layout = None
    if token is not None:
        layout = token.dataview
        if layout is not None:
            if layout.view_type in {"kanban", "gantt"}:
                return HttpResponse("This renderer requires a saved preference.", status=400)
            preference = _preference_from_layout(content_type, layout)
        elif token.preference_id is not None:
            # A verified embedding can reference a layout shared through a workspace.
            preference = get_object_or_404(
                UserListViewPreference, pk=token.preference_id, content_type=content_type,
            ).effective_preference

    manager = UserPolicyManager(request.user)
    queryset = manager.get_queryset(Model, BloomerpPermission.VIEW)
    if token is not None and token.relationship_field is not None:
        queryset = _scope_related_dataview(request, queryset, manager, token.relationship_field)
    if layout is not None and (config := get_model_config(Model)) and config.model_view_settings:
        scope = config.model_view_settings.embedded_queryset_scope
        if scope is not None:
            queryset = scope(request, queryset, layout.component_args)
    
    # Get preference and options
    if preference is None:
        preference = PreferenceManager(request.user).get_or_create_selected(
            UserListViewPreference,
            {"content_type_id": content_type.id},
        )
    elif preference.content_type_id != content_type.id:
        return HttpResponse("Invalid list view preference", status=400)
    dataview_options = layout if layout is not None else _get_dataview_options(preference)
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
        | set().union(*(
            entry.renderer_cls.get_reserved_query_params()
            for entry in DATAVIEW_REGISTRY.values()
        ))
    )
    filter_querydict = request_query_params(request)
    for key in reserved_query_keys:
        filter_querydict.pop(key, None)
    for key in list(filter_querydict.keys()):
        if key.startswith("_arg_"):
            filter_querydict.pop(key, None)
    if layout is None:
        filter_querydict = preference.apply_default_filters(filter_querydict)
    else:
        for key, value in layout.default_filters.items():
            filter_querydict.setlist(
                key, filter_querydict.getlist(key) + (value if isinstance(value, list) else [value])
            )
    
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

    if renderer_action is not None:
        calculate_count = definition.renderer_cls.action_requires_count(renderer_action)
    count = queryset.count() if calculate_count else 0
    object_actions = get_object_actions(
        Model, surface="dataview_item", group_all=definition.key == "calendar",
    )
    if token is not None and token.object_actions is not None:
        object_actions = [action for action in object_actions if action.id in token.object_actions]
    permission_fields = dataview_render_fields + ([avatar_field] if avatar_field else [])
    if any(
        isinstance(action, ObjectHTMLAction) and action.context_func is object_contact_context
        for action in iter_object_actions(object_actions)
    ):
        permission_fields.extend(get_object_contact_access(request).fields_for(Model))
    queryset = manager.annotate_field_permissions(
        queryset,
        permission_fields,
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
        object_actions=object_actions,
        layout_actions=token.dataview_actions if token is not None else None,
        create_url=token.create_url if token is not None else None,
        hide_filters=token.hide_filters if token is not None else False,
        query=query,
        context=renderer_context,
        count=count,
        filters=filters
    )


def _preference_from_layout(content_type: ContentType, layout: BaseDataview) -> UserListViewPreference:
    """Adapt a fixed layout for existing renderers without saving a user preference."""
    field_ids = dict(
        ApplicationField.objects.filter(
            content_type=content_type, field__in=layout.display_fields,
        ).values_list("field", "pk")
    )
    return UserListViewPreference(
        content_type=content_type,
        name=layout.name,
        view_type=layout.view_type,
        view_mode=layout.view_mode,
        display_fields={layout.view_type: [field_ids[name] for name in layout.display_fields if name in field_ids]},
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


def _get_dataview_options_initial(preference: UserListViewPreference, view_type: str) -> dict:
    definition = DATAVIEW_REGISTRY.get(view_type)
    if definition is None:
        return {}

    dataview_options = _get_dataview_options(preference, view_type)
    if dataview_options is None:
        return {}
    return dataview_options.dump_options()


def _get_dataview_options(
    preference: UserListViewPreference, view_type: str | None = None
) -> BaseDataview | None:
    """Returns the data view options for a specific preference type
    """
    view_type = view_type or preference.view_type
    definition = DATAVIEW_REGISTRY.get(view_type)
    if definition is None:
        return None

    raw_options = (preference.options or {}).get(view_type, {})
    options_model = definition.config_cls
    try:
        options = options_model.model_validate(raw_options or {})
        if view_type == preference.view_type and preference.view_mode not in {"normal", "split", "drawer"}:
            preference.view_mode = options.view_mode
        return options
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

    state.context = context
    return definition.renderer_cls(state).render(pagination)


def build_dataview_action_context(
    request: HttpRequest,
    state: DataviewState,
    *,
    render_id: str | None = None,
) -> DataviewActionContext:
    """Expose the active filters and accessible selection for Dataview actions."""
    values = request.POST if request.method == "POST" else request.GET
    selected_ids = values.getlist("selected_ids")
    try:
        normalized_ids = [state.model._meta.pk.to_python(value) for value in selected_ids]
    except (ValidationError, ValueError, TypeError):
        normalized_ids = []
    accessible_ids = {
        str(value) for value in state.queryset.filter(pk__in=normalized_ids).values_list("pk", flat=True)
    } if normalized_ids else set()
    query = request_query_params(request)
    query.pop(ACTION_DATAVIEW_PREFERENCE_PARAM, None)
    return DataviewActionContext(
        request=request,
        model=state.model,
        content_type=state.content_type,
        preference=state.preference,
        queryset=state.queryset,
        querystring=query.urlencode(),
        filters=state.filters or [],
        selected_ids=list(dict.fromkeys(str(value) for value in normalized_ids if str(value) in accessible_ids)),
        component_args=getattr(state.options, "component_args", {}),
        render_id=render_id,
        create_url=state.create_url,
    )


def _render_dataview_actions(
    action_context: DataviewActionContext,
    context: dict[str, Any],
    action_ids: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Render toolbar and selection controls with the same layout and visibility rules."""
    toolbar_actions: list[str] = []
    selection_actions: list[str] = []
    allowed_ids = set(action_ids) if action_ids is not None else None

    def execution_url(action_id: str) -> str:
        """Build a server-action URL scoped to this toolbar's dataview."""
        url = reverse(
            "components_dataview_action",
            kwargs={"content_type_id": action_context.content_type.pk, "action_id": action_id},
        )
        return with_dataview_context(url, action_context)

    template_context = {**context, "model": action_context.model}
    for action in get_dataview_actions(action_context.model):
        if action_context.preference.pk is None and action.id in {"display-options", "select-preference"}:
            continue
        if allowed_ids is not None and action.id not in allowed_ids:
            continue
        for selection_only, rendered_actions in ((False, toolbar_actions), (True, selection_actions)):
            markup = render_action(
                action, action_context, template_context, execution_url,
                selection_only=selection_only,
            )
            if not markup:
                continue
            if selection_only or not isinstance(action, DataviewHTMLAction):
                markup = render_to_string(
                    "components/objects/dataview_actions/action.html",
                    {
                        "action": action,
                        "action_markup": mark_safe(markup),
                        "selection_only": selection_only,
                    },
                    request=action_context.request,
                )
            rendered_actions.append(markup)

    return toolbar_actions, selection_actions
    


@router.register(
    path="components/dataview/<int:content_type_id>/",
    name="components_dataview",
)
def dataview(
    request: HttpRequest,
    content_type_id: int,
    preference: UserListViewPreference | None = None,
    *,
    actions: list[str] | None = None,
) -> HttpResponse:
    """Render a permission-filtered Dataview in its request context.

    A dataview can be of type:
        - table
        - kanban
        - card
        - ...

    Args:
        request (HttpRequest): request object
        content_type_id (int): content type id
        preference (UserListViewPreference | None, optional): Injected preference object. Defaults to None.
        actions (list[str] | None, optional): IDs of the actions to render. When
            omitted, all actions configured for the model are rendered.

    Returns:
        HttpResponse: The response
    """
    preference_was_explicit = preference is not None
    state = _build_dataview_state(request, content_type_id, preference)
    if isinstance(state, HttpResponse):
        return state

    context_id = request_token_id(request)
    if preference_was_explicit and request.user.is_authenticated and state.preference.pk is not None:
        token = get_token(request) or RequestToken()
        if token.operation_preferences.get(content_type_id) != state.preference.pk:
            token = token.model_copy(update={
                "operation_preferences": {**token.operation_preferences, content_type_id: state.preference.pk},
            })
            context_id = issue_token(token, request)

    definition = DATAVIEW_REGISTRY.get(state.preference.view_type)
    if definition is None:
        return HttpResponse("Invalid view type", status=400)

    pagination = definition.renderer_cls.paginate_queryset(
        state.queryset,
        state.preference,
        request,
        state.options,
    )
    
    page_querystring = request_query_params(request)
    page_querystring.pop('page', None)
    search_querystring = request_query_params(request)
    search_querystring.pop('page', None)
    search_querystring.pop('q', None)
    create_querystring = request_query_params(request)
    create_querystring.pop('page', None)
    create_querystring.pop('q', None)
    create_querystring.pop(DATAVIEW_PAGE_PARAM, None)
    for key in definition.renderer_cls.get_reserved_query_params():
        search_querystring.pop(key, None)
        create_querystring.pop(key, None)
    create_component_url = state.create_url
    render_id = str(uuid.uuid4())
    action_context = build_dataview_action_context(request, state, render_id=render_id)
    if create_component_url is None and can_create_dataview_object(action_context):
        create_component_url = reverse(
            "components_create_object", kwargs={"content_type_id": state.content_type.pk}
        )
        if create_querystring:
            create_component_url += f"?{create_querystring.urlencode()}"
    standalone = request.GET.get(DATAVIEW_PAGE_PARAM) == "true"
    sync_url = (
        standalone
        or request.headers.get("X-Bloomerp-Sync-Url", "false").lower() == "true"
        or definition.key == "file_browser"
    )
    container_component_id = request.GET.get("_component_id") or getattr(
        state.options, "container_component_id", None,
    )

    dataview_base_url = reverse(
        "components_dataview",
        kwargs={"content_type_id": content_type_id},
    )
    data_view_querystring = request_query_params(request).urlencode()
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
        'filter_host': state.preference if state.preference.pk is not None else None,
        'render_id': render_id,
        'record_based': definition.record_based,
        'search_query': state.query or '',
        'search_querystring': search_querystring.urlencode(),
        'create_querystring': create_querystring.urlencode(),
        'create_component_url': create_component_url,
        'sync_url': sync_url,
        'page_querystring': page_querystring.urlencode(),
        'pagination_pages': pagination.pagination_pages or [],
        'show_global_pagination': pagination.show_global_pagination,
        'container_component_id': container_component_id,
        'item_click_action_id': getattr(state.options, "item_click_action_id", None),
        'component_args': {
            **_get_component_args(request),
            **{key.replace("_", "-"): value for key, value in action_context.component_args.items()},
        },
        'object_actions' : state.object_actions,
        'view_types' : [vt for vt in DATAVIEW_REGISTRY.values() if vt.available_for_model(state.model)],
        'dataview_options_form': _get_dataview_options_form(
            state,
        ),
        'dataview_base_url': dataview_base_url,
        'data_view_url': data_view_url,
        'dataview_request_context_id': context_id,
        'request_context_headers': request_token_headers(context_id) if context_id else None,
        'renderer_operation_querystring': data_view_querystring,
        'initial_filters': request.GET.get('filter'),
        'hide_filters': (
            state.hide_filters or request.GET.get('_arg_hide_filters', '').lower() == 'true'
        ),
        'count' : state.count,
        'is_data_section_request': is_data_section_request,
        'filters' : state.filters
    }
    context.update(state.context)
    context["dataview_action_context"] = action_context
    if not is_data_section_request:
        toolbar_actions, selection_actions = _render_dataview_actions(
            action_context,
            context,
            state.layout_actions if state.layout_actions is not None else actions,
        )
        context["rendered_dataview_actions"] = toolbar_actions
        context["rendered_selection_actions"] = selection_actions
    context["rendered_dataview"] = _render_dataview_body(state, pagination, context)

    if standalone and (
        not request.htmx or request.htmx.history_restore_request or htmx_target == "main-content"
    ):
        return _DataviewPage.as_view()(
            request, model_label=str(state.model._meta.verbose_name_plural).title(), **context,
        )
    return render(request, 'components/objects/dataview.html', context)
