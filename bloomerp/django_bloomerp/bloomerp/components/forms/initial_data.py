from typing import Any
from uuid import uuid4

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.forms.form import Form
from bloomerp.router import router
from bloomerp.services.form_services import FormManager
from bloomerp.services.one_to_many_field_services import collect_submitted_one_to_many_data
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    get_layout_widget_attrs,
)


def _field_type_id(application_field: ApplicationField) -> str:
    try:
        return application_field.get_field_type_enum().value.id
    except (FieldDoesNotExist, ValueError):
        return application_field.field_type


def _layout_item_config(form: Form, application_field: ApplicationField) -> dict[str, Any]:
    for row in form.layout_obj.rows:
        for item in row.items:
            if str(item.id) in {str(application_field.pk), application_field.field}:
                return item.config if isinstance(item.config, dict) else {}
    return {}


def _child_field_options(form: Form, application_field: ApplicationField) -> list[dict[str, str]]:
    related_model = application_field.get_related_model()
    parent_model = form.content_type.model_class()
    if related_model is None or parent_model is None:
        return []

    layout_config = _layout_item_config(form, application_field)
    inline_fields = layout_config.get("inline_fields") if isinstance(layout_config, dict) else []
    child_content_type = ContentType.objects.get_for_model(related_model)
    queryset = ApplicationField.objects.filter(content_type=child_content_type)

    child_fields: list[ApplicationField]
    if isinstance(inline_fields, list) and inline_fields:
        fields_by_name = {
            field.field: field
            for field in queryset.filter(field__in=inline_fields)
            if not _is_parent_link_field(field, parent_model)
        }
        child_fields = [
            fields_by_name[field_name]
            for field_name in inline_fields
            if field_name in fields_by_name
        ]
    else:
        child_fields = [
            field
            for field in queryset.order_by("field")
            if _can_use_child_field(field, parent_model)
        ][:6]

    return [
        {
            "id": str(field.pk),
            "name": field.field,
            "title": field.title,
            "field_type": _field_type_id(field),
        }
        for field in child_fields
    ]


def _can_use_child_field(application_field: ApplicationField, parent_model) -> bool:
    if _is_parent_link_field(application_field, parent_model):
        return False
    try:
        model_field = application_field._get_model_field()
    except FieldDoesNotExist:
        return False
    if getattr(model_field, "auto_created", False):
        return False
    if not getattr(model_field, "editable", True):
        return False
    return bool(getattr(model_field, "concrete", True) or getattr(model_field, "many_to_many", False))


def _is_parent_link_field(application_field: ApplicationField, parent_model) -> bool:
    try:
        model_field = application_field._get_model_field()
    except FieldDoesNotExist:
        return False
    remote_field = getattr(model_field, "remote_field", None)
    return getattr(remote_field, "model", None) == parent_model


def _selectable_fields(form: Form) -> list[ApplicationField]:
    manager = FormManager(form)
    fields: list[ApplicationField] = []
    for field in ApplicationField.objects.filter(content_type=form.content_type).order_by("field"):
        field_type_id = _field_type_id(field)
        if field_type_id == "OneToManyField" or manager.can_use_model_form_field(field.field):
            fields.append(field)
    return fields


def _render_value_input(
    *,
    application_field: ApplicationField,
    input_name: str,
    value: Any = None,
    layout_config: dict[str, Any] | None = None,
) -> str:
    widget = application_field.get_widget(layout_config=layout_config)
    return widget.render(
        name=input_name,
        value=value,
        attrs=get_layout_widget_attrs(widget=widget),
    )


def _one_to_many_field_context(
    form: Form,
    application_field: ApplicationField,
    mode: str,
    child_field_name: str | None,
    row_id: str,
) -> dict[str, Any]:
    child_fields = _child_field_options(form, application_field)
    selected_child = next(
        (child for child in child_fields if child["name"] == child_field_name),
        child_fields[0] if child_fields else None,
    )
    child_application_field = None
    child_layout_context = {}
    initial_payload = form.initial_payload if isinstance(form.initial_payload, dict) else {}
    if selected_child:
        child_application_field = get_object_or_404(ApplicationField, pk=selected_child["id"])
        row_defaults = _one_to_many_payload_config(initial_payload.get(application_field.field)).get("row_defaults", {})
        child_layout_context = {
            "input": _render_value_input(
                application_field=child_application_field,
                input_name=f"value_{row_id}",
                value=row_defaults.get(selected_child["name"]),
            )
        }
    one_to_many_payload = _one_to_many_payload_config(initial_payload.get(application_field.field))
    table_layout_context = build_crud_layout_field_context(
        application_field=application_field,
        value=one_to_many_payload.get("initial_rows", []),
        layout_config=_layout_item_config(form, application_field),
    )
    return {
        "mode": mode,
        "child_fields": child_fields,
        "selected_child": selected_child,
        "child_application_field": child_application_field,
        "child_layout_context": child_layout_context,
        "table_layout_context": table_layout_context,
    }


def _one_to_many_payload_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "initial_rows": value.get("initial_rows", []) if isinstance(value.get("initial_rows"), list) else [],
            "row_defaults": value.get("row_defaults", {}) if isinstance(value.get("row_defaults"), dict) else {},
        }
    if isinstance(value, list):
        return {"initial_rows": value, "row_defaults": {}}
    return {"initial_rows": [], "row_defaults": {}}


def _posted_value(request: HttpRequest, name: str) -> Any:
    values = [value for value in request.POST.getlist(name) if value not in (None, "")]
    if len(values) > 1:
        return values
    if values:
        return values[0]
    return ""


def _save_initial_payload(form: Form, request: HttpRequest) -> None:
    selectable_fields = {str(field.pk): field for field in _selectable_fields(form)}
    payload: dict[str, Any] = {}
    one_to_many_modes: dict[str, set[str]] = {}

    for row_id in request.POST.getlist("row_id"):
        application_field = selectable_fields.get(request.POST.get(f"field_id_{row_id}"))
        if application_field is None:
            continue

        field_type_id = _field_type_id(application_field)
        if field_type_id != "OneToManyField":
            value = _posted_value(request, f"value_{row_id}")
            if value not in ("", [], None):
                payload[application_field.field] = value
            continue

        mode = request.POST.get(f"one_to_many_mode_{row_id}") or "row_defaults"
        one_to_many_modes.setdefault(application_field.field, set()).add(mode)
        if mode != "row_defaults":
            continue

        child_field_name = request.POST.get(f"child_field_{row_id}")
        value = _posted_value(request, f"value_{row_id}")
        if not child_field_name or value in ("", [], None):
            continue

        config = payload.setdefault(application_field.field, {"initial_rows": [], "row_defaults": {}})
        if not isinstance(config, dict):
            config = {"initial_rows": [], "row_defaults": {}}
            payload[application_field.field] = config
        config.setdefault("row_defaults", {})[child_field_name] = value

    parent_model = form.content_type.model_class()
    if parent_model is not None:
        initial_rows_by_field = collect_submitted_one_to_many_data(
            parent_model=parent_model,
            layout=form.layout_obj,
            submitted_data=request.POST,
        )
        for field_name, rows in initial_rows_by_field.items():
            if "initial_rows" not in one_to_many_modes.get(field_name, set()):
                continue
            existing = payload.get(field_name)
            if isinstance(existing, dict):
                existing["initial_rows"] = rows
            else:
                payload[field_name] = {"initial_rows": rows, "row_defaults": {}}

    compact_payload: dict[str, Any] = {}
    for field_name, value in payload.items():
        if isinstance(value, dict) and not value.get("row_defaults"):
            compact_payload[field_name] = value.get("initial_rows", [])
        else:
            compact_payload[field_name] = value

    form.initial_payload = compact_payload
    form.save(update_fields=["initial_payload"])


def _payload_rows(form: Form) -> list[dict[str, Any]]:
    fields_by_name = {field.field: field for field in _selectable_fields(form)}
    payload = form.initial_payload if isinstance(form.initial_payload, dict) else {}
    rows: list[dict[str, Any]] = []
    for field_name, value in payload.items():
        application_field = fields_by_name.get(field_name)
        if application_field is None:
            continue
        row_id = uuid4().hex
        if _field_type_id(application_field) != "OneToManyField":
            rows.append(
                {
                    "row_id": row_id,
                    "selected_field_id": str(application_field.pk),
                    "value_context": {
                        "form": form,
                        "application_field": application_field,
                        "field_type_id": _field_type_id(application_field),
                        "row_id": row_id,
                        "layout_context": {
                            "input": _render_value_input(
                                application_field=application_field,
                                input_name=f"value_{row_id}",
                                value=value,
                            )
                        },
                    },
                }
            )
            continue

        config = _one_to_many_payload_config(value)
        if config["initial_rows"]:
            rows.append(
                {
                    "row_id": row_id,
                    "selected_field_id": str(application_field.pk),
                    "value_context": {
                        "form": form,
                        "application_field": application_field,
                        "field_type_id": "OneToManyField",
                        "row_id": row_id,
                        **_one_to_many_field_context(form, application_field, "initial_rows", None, row_id),
                    },
                }
            )

        for child_field_name in config["row_defaults"].keys():
            row_id = uuid4().hex
            rows.append(
                {
                    "row_id": row_id,
                    "selected_field_id": str(application_field.pk),
                    "value_context": {
                        "form": form,
                        "application_field": application_field,
                        "field_type_id": "OneToManyField",
                        "row_id": row_id,
                        **_one_to_many_field_context(form, application_field, "row_defaults", child_field_name, row_id),
                    },
                }
            )
    return rows


@router.register(
    path="components/forms/<str:id>/initial-data/",
    url_name="components_forms_initial_data"
)
def initial_data(request:HttpRequest, id:str) -> HttpResponse:
    form = get_object_or_404(Form, id=id)
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)

    if request.method == "POST":
        _save_initial_payload(form, request)

    application_fields = _selectable_fields(form)
    rows = _payload_rows(form) or [{"row_id": uuid4().hex}]

    return render(
        request,
        "components/forms/initial_data.html",
        context={
            "form": form,
            "application_fields" : application_fields,
            "rows": rows,
            "form_content_type" : ContentType.objects.get_for_model(Form),
            "model_content_type" : form.content_type,
        }
    )


@router.register(
    path="components/forms/<str:id>/initial-data/row/",
    url_name="components_forms_initial_data_row"
)
def initial_data_row(request: HttpRequest, id: str) -> HttpResponse:
    form = get_object_or_404(Form, id=id)
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)

    return render(
        request,
        "components/forms/initial_data_row.html",
        context={
            "form": form,
            "application_fields": _selectable_fields(form),
            "row_id": uuid4().hex,
        },
    )


@router.register(
    path="components/forms/<str:id>/initial-data/value/",
    url_name="components_forms_initial_data_value"
)
def initial_data_value(request: HttpRequest, id: str) -> HttpResponse:
    form = get_object_or_404(Form, id=id)
    if not request.user.is_authenticated:
        return HttpResponse("Permission denied", status=403)

    field_id = request.GET.get("field_id") or request.GET.get(f"field_id_{request.GET.get('row_id')}")
    row_id = request.GET.get("row_id") or uuid4().hex
    if not field_id:
        return HttpResponse("", status=204)

    application_field = get_object_or_404(
        ApplicationField,
        pk=field_id,
        content_type=form.content_type,
    )
    field_type_id = _field_type_id(application_field)
    mode = request.GET.get("one_to_many_mode") or "row_defaults"
    if mode not in {"row_defaults", "initial_rows"}:
        mode = "row_defaults"
    child_field_name = request.GET.get("child_field") or request.GET.get(f"child_field_{row_id}")
    context = {
        "form": form,
        "application_field": application_field,
        "field_type_id": field_type_id,
        "row_id": row_id,
    }

    if field_type_id == "OneToManyField":
        context.update(_one_to_many_field_context(form, application_field, mode, child_field_name, row_id))
    else:
        initial_payload = form.initial_payload if isinstance(form.initial_payload, dict) else {}
        context.update(
            {
                "layout_context": {
                    "input": _render_value_input(
                        application_field=application_field,
                        input_name=f"value_{row_id}",
                        value=initial_payload.get(application_field.field),
                    )
                }
            }
        )

    return render(
        request,
        "components/forms/initial_data_value.html",
        context=context,
    )
