from django import forms
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.field_types.types import FieldType
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.router import router
from bloomerp.services.workspace_services import WorkspaceFilter, WorkspaceManager

URL_NAME = "components_filter_workspace"



def _render_is_null_widget(field_name: str) -> str:
    return forms.Select(
        choices=[
            ("true", "True"),
            ("false", "False"),
        ],
        attrs={"class": "select w-full"},
    ).render(name=field_name, value=None)


def _render_boolean_widget(field_name: str) -> str:
    return forms.Select(
        choices=[
            ("true", "True"),
            ("false", "False"),
        ],
        attrs={"class": "select w-full"},
    ).render(name=field_name, value=None)


def _render_month_widget(field_name: str) -> str:
    import calendar

    return forms.Select(
        choices=[(str(index), calendar.month_name[index]) for index in range(1, 13)],
        attrs={"class": "select w-full"},
    ).render(name=field_name, value=None)


def _render_number_widget(field_name: str, min_value: int | None = None, max_value: int | None = None) -> str:
    attrs = {"class": "input w-full"}
    if min_value is not None:
        attrs["min"] = min_value
    if max_value is not None:
        attrs["max"] = max_value

    return forms.NumberInput(attrs=attrs).render(name=field_name, value=None)


def _render_hidden_lookup_widget(field_name: str, helper_text: str) -> str:
    return (
        f'<input type="hidden" name="{field_name}" value="true">'
        f'<div class="input w-full">{helper_text}</div>'
    )


def _render_filter_value_widget(field: WorkspaceFilter, field_type: FieldType) -> str:
    widget = field_type.value.get_widget_cls()(attrs=field_type.value.default_widget_args.copy())
    widget_choices = getattr(widget, "get_choices", lambda *_args, **_kwargs: [])()

    input_class = (
        "select w-full"
        if isinstance(widget, forms.Select) or widget_choices
        else "input w-full"
    )

    return widget.render(
        name=field.field,
        value=None,
        attrs={
            "class": input_class,
        },
    )


def _render_workspace_filter_lookup_value(field: WorkspaceFilter, field_type: FieldType, lookup_id: str) -> str:
    if lookup_id == "is_null":
        return _render_is_null_widget(field.field)

    if field_type in {FieldType.BOOLEAN_FIELD, FieldType.NULL_BOOLEAN_FIELD}:
        return _render_boolean_widget(field.field)

    relative_date_helpers = {
        "today": "Uses today's date automatically.",
        "yesterday": "Uses yesterday's date automatically.",
        "this_week": "Uses the current week automatically.",
        "last_week": "Uses the previous week automatically.",
        "this_month": "Uses the current month automatically.",
        "last_month": "Uses the previous month automatically.",
        "this_quarter": "Uses the current quarter automatically.",
        "last_quarter": "Uses the previous quarter automatically.",
        "this_year": "Uses the current year automatically.",
        "last_year": "Uses the previous year automatically.",
    }
    if lookup_id in relative_date_helpers:
        return _render_hidden_lookup_widget(field.field, relative_date_helpers[lookup_id])

    if lookup_id == "year":
        return _render_number_widget(field.field, min_value=1)

    if lookup_id == "month":
        return _render_month_widget(field.field)

    if lookup_id == "day":
        return _render_number_widget(field.field, min_value=1, max_value=31)

    if lookup_id == "week":
        return _render_number_widget(field.field, min_value=1, max_value=53)

    return _render_filter_value_widget(field, field_type)


@router.register(
    path="components/workspaces/<int:workspace_id>/filters/init/",
    name="components_workspaces_filters_init",
)
def workspace_filters_init(request: HttpRequest, workspace_id: int) -> HttpResponse:
    workspace = get_object_or_404(Workspace, id=workspace_id)
    manager = WorkspaceManager(workspace)

    return render(
        request,
        "components/workspaces/filters/init.html",
        {
            "workspace": workspace,
            "filter_fields": manager.get_filter_fields(request.user),
        },
    )


@router.register(
    path="components/workspaces/<int:workspace_id>/filters/lookup-operators/<str:filter_key>/",
    name="components_workspaces_filters_lookup_operators",
)
def workspace_filters_lookup_operators(
    request: HttpRequest,
    workspace_id: int,
    filter_key: str,
) -> HttpResponse:
    workspace = get_object_or_404(Workspace, id=workspace_id)
    manager = WorkspaceManager(workspace)
    field = manager.get_filter_fields(request.user).get(filter_key)
    if field is None:
        return HttpResponse("Workspace filter field not found.", status=404)
    
    field_type = FieldType.from_id(field.type)
    return render(
        request,
        "components/workspaces/filters/lookup_operators.html",
        {
            "filter_field": field,
            "lookups": field_type.value.lookups,
        },
    )


@router.register(
    path="components/workspaces/<int:workspace_id>/filters/value-input/<str:filter_key>/",
    name="components_workspaces_filters_value_input",
)
def workspace_filters_value_input(
    request: HttpRequest,
    workspace_id: int,
    filter_key: str,
) -> HttpResponse:
    workspace = get_object_or_404(Workspace, id=workspace_id)
    manager = WorkspaceManager(workspace)
    field = manager.get_filter_fields(request.user).get(filter_key)
    if field is None:
        return HttpResponse("Workspace filter field not found.", status=404)

    lookup_value = request.GET.get("lookup_value", "")
    field_type = FieldType.from_id(field.type)
    lookup_option = next((option for option in field_type.value.lookups if option.value.id == lookup_value), None)

    if not lookup_option:
        return HttpResponse("Invalid lookup operator.", status=400)

    return HttpResponse(_render_workspace_filter_lookup_value(field, field_type, lookup_value))


@router.register(
    path="components/workspaces/<int:workspace_id>/filter",
    url_name=URL_NAME,
)
def filter_workspace(
    request: HttpRequest,
    workspace_id: int,
) -> HttpResponse:
    return workspace_filters_init(request, workspace_id)
