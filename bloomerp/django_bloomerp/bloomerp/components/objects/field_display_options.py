from __future__ import annotations

import json

from django.contrib.contenttypes.models import ContentType
from django.forms import Form
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from bloomerp.field_types import FieldTypeDefinition
from bloomerp.models import ApplicationField, UserCreateViewPreference
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem
from bloomerp.models.users.user_detail_view_preference import UserDetailViewPreference
from bloomerp.router import router
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import (
    build_crud_layout_field_context,
    get_object_field_value,
)
from bloomerp.utils.requests import render_blank_form, render_oob_swap


PREFERENCE_MODELS = {
    "create": UserCreateViewPreference,
    "detail": UserDetailViewPreference,
}


def create_form(field_type: FieldTypeDefinition, application_field: ApplicationField) -> type[Form]:
    attrs = {
        option.id: option.build_form_field(application_field)
        for option in field_type.field_display_options
    }
    return type("FieldDisplayForm", (Form,), attrs)


def _get_request_value(request: HttpRequest, key: str) -> str | None:
    return request.POST.get(key) or request.GET.get(key)


def _get_preference(request: HttpRequest):
    preference_scope = _get_request_value(request, "preference_scope") or "detail"
    preference_id = _get_request_value(request, "preference_id")
    preference_model = PREFERENCE_MODELS.get(preference_scope)
    if preference_model is None or not preference_id:
        return None, preference_scope
    return get_object_or_404(preference_model, pk=preference_id, user=request.user), preference_scope


def _find_layout_item(layout: FieldLayout, application_field: ApplicationField) -> LayoutItem | None:
    target_id = str(application_field.pk)
    for row in layout.rows:
        for item in row.items:
            if str(item.id) == target_id:
                return item
    return None


def _get_item_config(preference, application_field: ApplicationField) -> dict:
    item = _find_layout_item(preference.field_layout_obj, application_field)
    if item is None:
        return {}
    return item.config if isinstance(item.config, dict) else {}


def _save_item_config(preference, application_field: ApplicationField, config: dict) -> None:
    layout = preference.field_layout_obj
    item = _find_layout_item(layout, application_field)
    if item is None:
        return
    item.config = config
    preference.field_layout = layout.model_dump()
    preference.save(update_fields=["field_layout"])


def _build_initial_config(field_type: FieldTypeDefinition, config: dict) -> dict:
    return {
        option.id: config.get(option.id, option.default)
        for option in field_type.field_display_options
    }


def _merge_cleaned_config(field_type: FieldTypeDefinition, current_config: dict, cleaned_data: dict) -> dict:
    next_config = dict(current_config)
    for option in field_type.field_display_options:
        value = cleaned_data.get(option.id)
        if value in (None, "", []):
            next_config.pop(option.id, None)
        else:
            next_config[option.id] = value
    return next_config


def _render_field_oob(
    *,
    request: HttpRequest,
    preference,
    preference_scope: str,
    application_field: ApplicationField,
    object_id: str | None,
    layout_edit_mode: bool = False,
) -> HttpResponse | None:
    if preference_scope != "detail" or not object_id:
        return None

    model = application_field.get_model()
    permission_manager = UserPermissionManager(request.user)
    view_permission = create_permission_str(model, "view")
    obj = get_object_or_404(permission_manager.get_queryset(model, view_permission), pk=object_id)
    config = _get_item_config(preference, application_field)
    field_context = build_crud_layout_field_context(
        application_field=application_field,
        value=get_object_field_value(obj=obj, application_field=application_field),
        can_edit=permission_manager.has_field_permission(
            application_field,
            create_permission_str(model, "change"),
        ),
        layout_config=config,
    )
    content = render_to_string(
        "inclusion_tags/layout_field.html",
        {
            **field_context,
            "colspan": _get_layout_item_colspan(preference.field_layout_obj, application_field),
            "layout_preference_object": preference,
            "layout_mode": preference_scope,
            "layout_edit_mode": layout_edit_mode,
            "object_id": object_id,
            "non_required_fields_visible": "true",
        },
        request=request,
    )
    return render_oob_swap(
        request,
        template_name="inclusion_tags/layout_field.html",
        target_id=f"layout-field-{application_field.pk}",
        swap="outerHTML",
        content=content,
    )


def _get_layout_item_colspan(layout: FieldLayout, application_field: ApplicationField) -> int:
    item = _find_layout_item(layout, application_field)
    return item.colspan if item is not None else 1


def _user_can_configure_field(request: HttpRequest, preference, preference_scope: str, application_field: ApplicationField) -> bool:
    if application_field.content_type_id != preference.content_type_id:
        return False
    if request.user.is_superuser:
        return True

    model = preference.content_type.model_class()
    if model is None:
        return False

    if preference_scope == "create":
        return application_field.field in {
            field.field
            for field in get_addable_fields(content_type=preference.content_type, user=request.user)
        }

    permission_manager = UserPermissionManager(request.user)
    return permission_manager.has_field_permission(
        application_field,
        create_permission_str(model, "view"),
    )


@router.register(
    path="components/field_display_options/<int:application_field_id>/",
    name="components_field_display_options",
)
def field_display_options(request: HttpRequest, application_field_id: int):
    application_field = get_object_or_404(ApplicationField, id=application_field_id)
    preference, preference_scope = _get_preference(request)
    if preference is None:
        return HttpResponse("Missing display preference", status=400)
    if not _user_can_configure_field(request, preference, preference_scope, application_field):
        return HttpResponse("Permission denied", status=403)

    field_type = application_field.get_field_type_enum().value
    if not field_type.field_display_options:
        return HttpResponse("This field does not have display options.")

    form_class = create_form(field_type, application_field)
    current_config = _get_item_config(preference, application_field)
    hidden_args = {
        "preference_id": preference.pk,
        "preference_scope": preference_scope,
        "object_id": _get_request_value(request, "object_id") or "",
        "layout_edit_mode": _get_request_value(request, "layout_edit_mode") or "",
    }
    url = reverse(
        "components_field_display_options",
        kwargs={"application_field_id": application_field_id},
    )

    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid():
            next_config = _merge_cleaned_config(field_type, current_config, form.cleaned_data)
            _save_item_config(preference, application_field, next_config)
            field_oob = _render_field_oob(
                request=request,
                preference=preference,
                preference_scope=preference_scope,
                application_field=application_field,
                object_id=hidden_args["object_id"],
                layout_edit_mode=hidden_args["layout_edit_mode"].lower() == "true",
            )
            response_html = render_to_string(
                "cotton/ui/message.html",
                {
                    "text": "Display options saved.",
                    "type": "success",
                    "duration": 4,
                },
                request=request,
            )
            if field_oob is not None:
                response_html += field_oob.content.decode()
            response = HttpResponse(response_html)
            response["HX-Trigger-After-Swap"] = json.dumps(
                {
                    "bloomerp:close-modal": {
                        "modalId": "field-display-option-modal",
                    },
                    "bloomerp:layout-field-updated": {
                        "fieldId": str(application_field.pk),
                    }
                }
            )
            return response
    else:
        form = form_class(initial=_build_initial_config(field_type, current_config))

    return render_blank_form(
        request,
        form,
        url,
        hidden_args=hidden_args,
        submit_label="Save display options",
    )
