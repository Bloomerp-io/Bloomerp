import json
from dataclasses import dataclass

from django import forms
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from bloomerp.components.objects.dataviews.dataview import (
    _apply_default_filters_to_querydict,
    _normalize_default_filters,
)
from bloomerp.dataviews.registry import DATAVIEW_REGISTRY
from bloomerp.models import ApplicationField
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.bulk_action_services import (
    execute_bulk_delete,
    execute_bulk_update,
)
from bloomerp.services.object_services import string_search_on_queryset
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.services.user_services import get_data_view_fields
from bloomerp.utils.async_utils import run_async_or_sync
from bloomerp.filters.manager import ModelFilterManager
from bloomerp.utils.models import get_model_and_content_type_or_404
from bloomerp.utils.requests import render_message


RESERVED_BULK_QUERY_KEYS = {
    "action",
    "application_field_id",
    "csrfmiddlewaretoken",
    "object_ids",
    "page",
    "q",
    "selection",
    "_component_id",
}

@dataclass
class BulkActionState:
    model: type[models.Model]
    content_type: ContentType
    queryset: QuerySet
    permission: BloomerpPermission
    object_ids: list[str]
    filter_querystring: str
    query_summary: list[tuple[str, list[str]]]
    selection_label: str


class BulkActionForm(forms.Form):
    application_field_id = forms.ChoiceField(label="Field")

    def __init__(
        self,
        *args,
        fields: list[ApplicationField],
        field_selector_url: str,
        selected_field: ApplicationField | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["application_field_id"].choices = [
            (str(field.id), field.title)
            for field in fields
        ]
        self.fields["application_field_id"].widget.attrs.update(
            {
                "class": "select select-bordered w-full",
                "hx-get": field_selector_url,
                "hx-target": "#bulk-action-field-value",
                "hx-include": "closest form",
                "hx-swap": "innerHTML",
            }
        )
        if selected_field is not None:
            self.fields["application_field_id"].initial = str(selected_field.id)


def _editable_fields(
    request: HttpRequest,
    model: type[models.Model],
    content_type: ContentType,
) -> list[ApplicationField]:
    permission_manager = UserPolicyManager(request.user)
    dataview_fields = get_data_view_fields(
        PreferenceManager(request.user).get_or_create_selected(
            UserListViewPreference,
            scope={"content_type_id": content_type.id},
        )
    )
    accessible_fields = [field for field, _is_visible in dataview_fields.accessible_fields]
    editable_fields: list[ApplicationField] = []

    for application_field in accessible_fields:
        if not permission_manager.has_field_permission(
            application_field,
            BloomerpPermission.CHANGE,
        ):
            continue
        try:
            model_field = model._meta.get_field(application_field.field)
        except FieldDoesNotExist:
            continue
        if not getattr(model_field, "editable", False):
            continue
        if application_field.get_form_field() is None:
            continue
        editable_fields.append(application_field)

    return editable_fields


def _filter_querydict(request: HttpRequest, preference: UserListViewPreference):
    querydict = request.GET.copy()
    reserved_keys = set(RESERVED_BULK_QUERY_KEYS)
    definition = DATAVIEW_REGISTRY.get(preference.view_type)
    if definition is not None:
        reserved_keys |= definition.renderer_cls.get_reserved_query_params()

    for key in reserved_keys:
        querydict.pop(key, None)
    for key in list(querydict.keys()):
        if key.startswith("_arg_"):
            querydict.pop(key, None)
    return _apply_default_filters_to_querydict(
        querydict,
        _normalize_default_filters(preference.default_filters or {}),
    )


def _query_summary(filter_querydict) -> list[tuple[str, list[str]]]:
    return [
        (key, filter_querydict.getlist(key))
        for key in filter_querydict.keys()
    ]


def _field_selector_url(request: HttpRequest, content_type_id: int) -> str:
    querydict = request.GET.copy()
    querydict.pop("application_field_id", None)
    querydict.pop("csrfmiddlewaretoken", None)
    base_url = reverse(
        "components_bulk_actions_field_selector",
        kwargs={"content_type_id": content_type_id},
    )
    querystring = querydict.urlencode()
    return f"{base_url}?{querystring}" if querystring else base_url


def _build_bulk_action_state(
    request: HttpRequest,
    content_type_id: int,
    permission: BloomerpPermission,
) -> BulkActionState | HttpResponse:
    """Creates the bulk action state

    Args:
        request (HttpRequest): request
        content_type_id (int): content type id
        permission (BloomerpPermission): the bulk action permission

    Returns:
        BulkActionState | HttpResponse: the state
    """
    model, content_type = get_model_and_content_type_or_404(content_type_id)
    permission_manager = UserPolicyManager(request.user)
    preference = PreferenceManager(request.user).get_or_create_selected(
        UserListViewPreference,
        scope={"content_type_id": content_type.id},
    )

    if not permission_manager.has_global_permission(model, permission):
        return render(request, "403.html", status=403)

    queryset = permission_manager.get_accessible_queryset(model, permission)
    query = request.GET.get("q")
    if query:
        queryset = string_search_on_queryset(queryset, query)

    filter_querydict = _filter_querydict(request, preference)
    queryset = ModelFilterManager(model).filter(filter_querydict, queryset=queryset)

    object_ids = request.GET.getlist("object_ids")
    selection = request.GET.get("selection")
    if object_ids:
        queryset = queryset.filter(pk__in=object_ids)
    elif selection == "selected":
        queryset = queryset.none()

    return BulkActionState(
        model=model,
        content_type=content_type,
        queryset=queryset,
        permission=permission,
        object_ids=object_ids,
        filter_querystring=filter_querydict.urlencode(),
        query_summary=_query_summary(filter_querydict),
        selection_label="current selection" if selection == "selected" or object_ids else "all filtered records",
    )


def _get_selected_field(
    request: HttpRequest,
    content_type: ContentType,
    editable_fields: list[ApplicationField],
) -> ApplicationField | None:
    field_id = request.GET.get("application_field_id") or request.POST.get("application_field_id")
    if not field_id:
        return editable_fields[0] if editable_fields else None

    allowed_ids = {str(field.id) for field in editable_fields}
    if str(field_id) not in allowed_ids:
        return None

    return get_object_or_404(ApplicationField, id=field_id, content_type=content_type)


def _field_value_form_field(application_field: ApplicationField) -> forms.Field:
    form_field = application_field.get_form_field()
    form_field.label = f"New {application_field.title}"
    form_field.required = False
    form_field.widget.attrs.update({"class": "input input-bordered w-full"})
    return form_field


def _field_value_bound_field(application_field: ApplicationField):
    form = forms.Form()
    form.fields["value"] = _field_value_form_field(application_field)
    return form["value"]


def _render_field_selector(request: HttpRequest, application_field: ApplicationField) -> HttpResponse:
    return render(
        request,
        "components/objects/bulk_action_field.html",
        {
            "field": _field_value_bound_field(application_field),
            "application_field": application_field,
        },
    )


def _run_bulk_update(
    *,
    request: HttpRequest,
    content_type_id: int,
    application_field: ApplicationField,
    object_ids: list[str],
    raw_value,
) -> tuple[str, int]:
    ran_async, result = run_async_or_sync(
        execute_bulk_update,
        content_type_id=content_type_id,
        user_id=request.user.pk,
        application_field_id=application_field.pk,
        object_ids=object_ids,
        value=raw_value,
    )
    return ("queued", len(object_ids)) if ran_async else ("completed", result)


def _run_bulk_delete(
    *,
    request: HttpRequest,
    content_type_id: int,
    object_ids: list[str],
) -> tuple[str, int]:
    """Queue a bulk delete when possible, otherwise perform it synchronously."""
    ran_async, result = run_async_or_sync(
        execute_bulk_delete,
        content_type_id=content_type_id,
        user_id=request.user.pk,
        object_ids=object_ids,
    )
    return ("queued", len(object_ids)) if ran_async else ("completed", result)


@router.register(
    path="components/dataview/<int:content_type_id>/bulk_actions/",
    url_name="components_bulk_actions",
)
def bulk_actions(request: HttpRequest, content_type_id: int) -> HttpResponse:
    if request.method not in {"GET", "POST"}:
        return HttpResponse("Method not allowed", status=405)

    model, _content_type = get_model_and_content_type_or_404(content_type_id)
    permission_manager = UserPolicyManager(request.user)
    can_bulk_update = permission_manager.has_global_permission(
        model,
        BloomerpPermission.BULK_CHANGE,
    )
    can_bulk_delete = permission_manager.has_global_permission(
        model,
        BloomerpPermission.BULK_DELETE,
    )
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            permission = BloomerpPermission[action.upper()] if action else None
        except KeyError:
            permission = None
    else:
        permission = (
            BloomerpPermission.BULK_CHANGE
            if can_bulk_update
            else BloomerpPermission.BULK_DELETE
        )

    if permission not in {
        BloomerpPermission.BULK_CHANGE,
        BloomerpPermission.BULK_DELETE,
    }:
        return HttpResponse("Invalid bulk action", status=400)

    state = _build_bulk_action_state(request, content_type_id, permission)
    if isinstance(state, HttpResponse):
        return state

    if request.method == "POST":
        if not state.queryset.exists():
            return HttpResponse("No objects selected", status=400)

        object_ids = [
            str(pk)
            for pk in state.queryset.values_list("pk", flat=True)
        ]
        if permission == BloomerpPermission.BULK_DELETE:
            status, count = _run_bulk_delete(
                request=request,
                content_type_id=content_type_id,
                object_ids=object_ids,
            )
        else:
            editable_fields = _editable_fields(
                request,
                state.model,
                state.content_type,
            )
            selected_field = _get_selected_field(
                request,
                state.content_type,
                editable_fields,
            )
            if selected_field is None:
                return HttpResponse("Invalid field", status=400)

            values = request.POST.getlist("value")
            value = values if len(values) > 1 else request.POST.get("value")
            status, count = _run_bulk_update(
                request=request,
                content_type_id=content_type_id,
                application_field=selected_field,
                object_ids=object_ids,
                raw_value=value,
            )
        
        response = render_message(
            request,
            f"{permission.value.name} {status} for {count} object(s).",
            "info"
        )
        
        response["HX-Trigger-After-Swap"] = json.dumps(
            {
                "bloomerp:close-modal": {"modalId": "bulk-actions-modal"},
                "bloomerp:bulk-action-complete": {"contentTypeId": str(content_type_id)},
            }
        )
        return response

    update_state = (
        _build_bulk_action_state(
            request,
            content_type_id,
            BloomerpPermission.BULK_CHANGE,
        )
        if can_bulk_update
        else None
    )
    delete_state = (
        _build_bulk_action_state(
            request,
            content_type_id,
            BloomerpPermission.BULK_DELETE,
        )
        if can_bulk_delete
        else None
    )
    editable_fields = (
        _editable_fields(request, state.model, state.content_type)
        if can_bulk_update
        else []
    )
    selected_field = (
        _get_selected_field(request, state.content_type, editable_fields)
        if can_bulk_update
        else None
    )
    form = (
        BulkActionForm(
            fields=editable_fields,
            field_selector_url=_field_selector_url(request, content_type_id),
            selected_field=selected_field,
        )
        if can_bulk_update
        else None
    )
    return render(
        request,
        "components/objects/bulk_actions.html",
        {
            "content_type_id": content_type_id,
            "content_type": state.content_type,
            "form": form,
            "can_bulk_update": can_bulk_update,
            "can_bulk_delete": can_bulk_delete,
            "selected_field": selected_field,
            "selected_field_value": _field_value_bound_field(selected_field) if selected_field else None,
            "count": state.queryset.count(),
            "update_count": update_state.queryset.count() if isinstance(update_state, BulkActionState) else 0,
            "delete_count": delete_state.queryset.count() if isinstance(delete_state, BulkActionState) else 0,
            "query_summary": state.query_summary,
            "query_search": request.GET.get("q", ""),
            "selection_label": state.selection_label,
            "object_ids": state.object_ids,
            "submit_url": request.get_full_path(),
        },
    )


@router.register(
    path="components/dataview/<int:content_type_id>/bulk_actions/field_selector/",
    url_name="components_bulk_actions_field_selector",
)
def field_selector(request: HttpRequest, content_type_id: int) -> HttpResponse:
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
