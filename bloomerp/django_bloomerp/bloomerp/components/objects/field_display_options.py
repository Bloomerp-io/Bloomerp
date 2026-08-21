from __future__ import annotations

from dataclasses import dataclass

from django.contrib.contenttypes.models import ContentType
from django.forms import Form as DjangoForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from bloomerp.field_types.types import FieldTypeDefinition
from bloomerp.models import ApplicationField
from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem
from bloomerp.models.forms.form import Form
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget


LAYOUT_OBJECT_MODELS = {
    Form,
    UserObjectLayoutPreference,
}


@dataclass
class LayoutConfigTarget:
    layout_object: ContentLayoutModelMixin
    content_type: ContentType


def _layout_field_catalog(target: LayoutConfigTarget) -> list[dict[str, object]]:
    from bloomerp.field_types.types import build_behavior_catalog_entry

    ordered_items = [
        item
        for row in target.layout_object.layout_obj.rows
        for item in row.items
        if item.id not in (None, "")
    ]
    ordered_ids = [str(item.id) for item in ordered_items]
    numeric_ids = [item_id for item_id in ordered_ids if item_id.isdigit()]
    field_names = [item_id for item_id in ordered_ids if not item_id.isdigit()]
    queryset = ApplicationField.objects.filter(content_type=target.content_type)
    fields_by_id = {str(field.pk): field for field in queryset.filter(pk__in=numeric_ids)}
    fields_by_name = {field.field: field for field in queryset.filter(field__in=field_names)}

    catalog = []
    seen = set()
    for item in ordered_items:
        item_id = str(item.id)
        field = fields_by_id.get(item_id) or fields_by_name.get(item_id)
        if field is None or field.pk in seen:
            continue
        seen.add(field.pk)
        catalog.append(build_behavior_catalog_entry(field, item.config))
    return catalog


def create_form(
    field_type: FieldTypeDefinition,
    application_field: ApplicationField,
    target: LayoutConfigTarget | None = None,
) -> type[DjangoForm]:
    attrs = {
        option.id: option.build_form_field(application_field)
        for option in field_type.field_display_options
    }
    if target is not None:
        field_catalog = _layout_field_catalog(target)
        for form_field in attrs.values():
            if isinstance(form_field.widget, BehaviorBuilderWidget):
                form_field.widget.field_catalog = field_catalog
    return type("FieldDisplayForm", (DjangoForm,), attrs)


def _get_request_value(request: HttpRequest, key: str) -> str | None:
    return request.POST.get(key) or request.GET.get(key)


def _get_layout_config_target(request: HttpRequest) -> LayoutConfigTarget | None:
    layout_object_content_type_id = _get_request_value(request, "layout_object_content_type_id")
    layout_object_id = _get_request_value(request, "layout_object_id")

    if not layout_object_content_type_id or not layout_object_id:
        return None

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


def _user_can_configure_field(request: HttpRequest, target: LayoutConfigTarget, application_field: ApplicationField) -> bool:
    if application_field.content_type_id != target.content_type.id:
        return False
    if request.user.is_superuser:
        return True

    layout_object = target.layout_object
    if isinstance(layout_object, UserObjectLayoutPreference) and layout_object.user_id != request.user.id:
        return False

    model = target.content_type.model_class()
    if model is None:
        return False

    if isinstance(layout_object, Form):
        manager = UserPolicyManager(request.user)
        if not manager.has_access_to_object(layout_object, BloomerpPermission.CHANGE):
            return False
        accessible_fields = manager.get_accessible_fields(
            target.content_type,
            BloomerpPermission.ADD
        )
        return accessible_fields.filter(pk=application_field.pk).exists()

    manager = UserPolicyManager(request.user)
    return manager.has_field_permission(
        application_field,
        BloomerpPermission.VIEW
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

    form_class = create_form(field_type, application_field, target=target)
    current_config = _get_item_config(target.layout_object, application_field)
    hidden_args = {
        "layout_object_content_type_id": ContentType.objects.get_for_model(target.layout_object.__class__).pk,
        "layout_object_id": target.layout_object.pk,
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
            response_html = render_to_string(
                "cotton/ui/message.html",
                {
                    "text": "Display options saved.",
                    "type": "success",
                    "duration": 4,
                },
                request=request,
            )
            response = HttpResponse(response_html)
            return response
    else:
        form = form_class(initial=_build_initial_config(field_type, current_config))

    return render_blank_form(
        request,
        form,
        url,
        hidden_args=hidden_args,
        submit_label="Save display options",
        text="Configure how this field is displayed and behaves on the form.",
    )
