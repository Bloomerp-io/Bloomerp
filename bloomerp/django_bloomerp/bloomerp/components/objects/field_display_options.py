from __future__ import annotations

import json
from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.forms import Form as DjangoForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from bloomerp.field_types import FieldTypeDefinition
from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models import ApplicationField, UserCreateViewPreference
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem
from bloomerp.models.forms.form import Form
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.users.base_view_preference import BaseViewPreference
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
LAYOUT_OBJECT_MODELS = {
    Form,
    UserCreateViewPreference,
    UserDetailViewPreference,
}


@dataclass
class LayoutConfigTarget:
    layout_object: ContentLayoutModelMixin
    content_type: ContentType
    scope: str


def create_form(field_type: FieldTypeDefinition, application_field: ApplicationField) -> type[DjangoForm]:
    attrs = {
        option.id: option.build_form_field(application_field)
        for option in field_type.field_display_options
    }
    return type("FieldDisplayForm", (DjangoForm,), attrs)


def _get_request_value(request: HttpRequest, key: str) -> str | None:
    return request.POST.get(key) or request.GET.get(key)


def _get_legacy_preference(request: HttpRequest):
    preference_scope = _get_request_value(request, "preference_scope") or "detail"
    preference_id = _get_request_value(request, "preference_id")
    preference_model = PREFERENCE_MODELS.get(preference_scope)
    if preference_model is None or not preference_id:
        return None, preference_scope
    return get_object_or_404(preference_model, pk=preference_id, user=request.user), preference_scope


def _get_layout_config_target(request: HttpRequest) -> LayoutConfigTarget | None:
    scope = _get_request_value(request, "layout_mode") or _get_request_value(request, "preference_scope") or "detail"
    layout_object_content_type_id = _get_request_value(request, "layout_object_content_type_id")
    layout_object_id = _get_request_value(request, "layout_object_id")

    if layout_object_content_type_id and layout_object_id:
        content_type = get_object_or_404(ContentType, pk=layout_object_content_type_id)
        model = content_type.model_class()
        if model not in LAYOUT_OBJECT_MODELS:
            return None

        layout_object = get_object_or_404(model, pk=layout_object_id)
        target_content_type = getattr(layout_object, "content_type", None)
        if not isinstance(target_content_type, ContentType):
            return None

        return LayoutConfigTarget(
            layout_object=layout_object,
            content_type=target_content_type,
            scope=scope,
        )

    preference, preference_scope = _get_legacy_preference(request)
    if preference is None:
        return None
    return LayoutConfigTarget(
        layout_object=preference,
        content_type=preference.content_type,
        scope=preference_scope,
    )


def _find_layout_item(layout: FieldLayout, application_field: ApplicationField) -> LayoutItem | None:
    target_id = str(application_field.pk)
    for row in layout.rows:
        for item in row.items:
            if str(item.id) == target_id:
                return item
    return None


def _get_item_config(layout_object: ContentLayoutModelMixin, application_field: ApplicationField) -> dict:
    item = _find_layout_item(layout_object.layout_obj, application_field)
    if item is None:
        return {}
    return item.config if isinstance(item.config, dict) else {}


def _save_item_config(layout_object: ContentLayoutModelMixin, application_field: ApplicationField, config: dict) -> None:
    layout = layout_object.layout_obj
    item = _find_layout_item(layout, application_field)
    if item is None:
        return
    item.config = config
    layout_object.layout = layout.model_dump()
    layout_object.save(update_fields=["layout"])


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
    target: LayoutConfigTarget,
    application_field: ApplicationField,
    object_id: str | None,
    layout_edit_mode: bool = False,
) -> HttpResponse | None:
    model = application_field.get_model()
    permission_manager = UserPermissionManager(request.user)
    config = _get_item_config(target.layout_object, application_field)
    field_type = application_field.get_field_type_enum().value

    if target.scope == "detail" and object_id:
        view_permission = create_permission_str(model, "view")
        obj = get_object_or_404(permission_manager.get_queryset(model, view_permission), pk=object_id)
        field_context = build_crud_layout_field_context(
            application_field=application_field,
            value=get_object_field_value(obj=obj, application_field=application_field),
            can_edit=permission_manager.has_field_permission(
                application_field,
                create_permission_str(model, "change"),
            ),
            layout_config=config,
        )
    elif field_type.allow_in_model:
        addable_fields = list(get_addable_fields(content_type=target.content_type, user=request.user))
        allowed_field_names = [field.field for field in addable_fields]
        form_class = bloomerp_modelform_factory(model_cls=model, fields=allowed_field_names)
        form = form_class()
        if application_field.field not in form.fields:
            return None
        field_context = build_crud_layout_field_context(
            application_field=application_field,
            bound_field=form[application_field.field],
            layout_config=config,
        )
    elif field_type.editable_without_form_field:
        field_context = build_crud_layout_field_context(
            application_field=application_field,
            value=None,
            can_edit=True,
            layout_config=config,
        )
    else:
        return None

    content = render_to_string(
        "inclusion_tags/layout_field.html",
        {
            **field_context,
            "colspan": _get_layout_item_colspan(target.layout_object.layout_obj, application_field),
            "layout_object_content_type_id": ContentType.objects.get_for_model(target.layout_object.__class__).pk,
            "layout_object_id": target.layout_object.pk,
            "layout_preference_object": target.layout_object if isinstance(target.layout_object, BaseViewPreference) else None,
            "layout_mode": target.scope,
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


def _user_can_configure_field(request: HttpRequest, target: LayoutConfigTarget, application_field: ApplicationField) -> bool:
    if application_field.content_type_id != target.content_type.id:
        return False
    if request.user.is_superuser:
        return True

    layout_object = target.layout_object
    if isinstance(layout_object, BaseViewPreference) and layout_object.user_id != request.user.id:
        return False

    model = target.content_type.model_class()
    if model is None:
        return False

    if isinstance(layout_object, Form):
        manager = UserPermissionManager(request.user)
        if not manager.has_access_to_object(layout_object, create_permission_str(layout_object, "change")):
            return False
        return application_field.field in {
            field.field
            for field in get_addable_fields(content_type=target.content_type, user=request.user)
        }

    if target.scope == "create":
        return application_field.field in {
            field.field
            for field in get_addable_fields(content_type=target.content_type, user=request.user)
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
    target = _get_layout_config_target(request)
    if target is None:
        return HttpResponse("Missing layout object", status=400)
    if not _user_can_configure_field(request, target, application_field):
        return HttpResponse("Permission denied", status=403)

    field_type = application_field.get_field_type_enum().value
    if not field_type.field_display_options:
        return HttpResponse("This field does not have display options.")

    form_class = create_form(field_type, application_field)
    current_config = _get_item_config(target.layout_object, application_field)
    hidden_args = {
        "layout_object_content_type_id": ContentType.objects.get_for_model(target.layout_object.__class__).pk,
        "layout_object_id": target.layout_object.pk,
        "layout_mode": target.scope,
        "preference_id": getattr(target.layout_object, "pk", ""),
        "preference_scope": target.scope,
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
            _save_item_config(target.layout_object, application_field, next_config)
            field_oob = _render_field_oob(
                request=request,
                target=target,
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
