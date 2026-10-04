from __future__ import annotations
from bloomerp.field_types.display_options import FieldDisplayOption, LABEL_OPTION
from bloomerp.form_fields.behavior_field import BehaviorField
from bloomerp.widgets.behavior_builder_widget import BehaviorBuilderWidget
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget
from bloomerp.widgets.ordered_field_select_widget import OrderedFieldSelectWidget
from django import forms
from django.db import models
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


def get_related_model_field_choices(
    application_field: "ApplicationField",
) -> dict[str, Any]:
    from bloomerp.models import ApplicationField
    from django.contrib.contenttypes.models import ContentType

    related_model = application_field.get_related_model()
    if related_model is None:
        return {"choices": []}
    content_type = ContentType.objects.get_for_model(related_model)
    choices = []
    required_values = []
    parent_model = application_field.get_model()
    for related_field in ApplicationField.objects.filter(
        content_type=content_type
    ).order_by("field"):
        if _is_parent_link_field(related_field, parent_model):
            continue
        try:
            model_field = related_field._get_model_field()
        except Exception:
            continue
        if getattr(model_field, "auto_created", False):
            continue
        if not getattr(model_field, "editable", True):
            continue
        if not getattr(model_field, "concrete", True):
            continue
        choices.append((related_field.field, related_field.title))
        if _is_required_inline_field(related_field):
            required_values.append(related_field.field)
    return {
        "choices": choices,
        "widget": OrderedFieldSelectWidget(
            choices=choices, required_values=required_values
        ),
        "required_values": required_values,
    }


def _is_required_inline_field(application_field: "ApplicationField") -> bool:
    try:
        model_field = application_field._get_model_field()
    except Exception:
        return False
    return (
        not getattr(model_field, "blank", False)
        and (not getattr(model_field, "null", False))
        and (not getattr(model_field, "auto_created", False))
    )


def _is_parent_link_field(
    application_field: "ApplicationField", parent_model: type[models.Model] | None
) -> bool:
    if parent_model is None:
        return False
    try:
        model_field = application_field._get_model_field()
    except Exception:
        return False
    remote_field = getattr(model_field, "remote_field", None)
    return getattr(remote_field, "model", None) == parent_model


def get_behavior_form_field_kwargs(
    application_field: "ApplicationField",
) -> dict[str, Any]:
    from bloomerp.models import ApplicationField

    fields = [
        build_behavior_catalog_entry(field)
        for field in ApplicationField.objects.filter(
            content_type=application_field.content_type
        ).order_by("field")
    ]
    return {
        "widget": BehaviorBuilderWidget(
            source_field={
                "id": str(application_field.pk),
                "label": application_field.title,
                "fieldType": next(
                    (
                        field["fieldType"]
                        for field in fields
                        if field["id"] == str(application_field.pk)
                    ),
                    application_field.field_type,
                ),
            },
            field_catalog=fields,
        )
    }


def build_behavior_catalog_entry(
    application_field: "ApplicationField", layout_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Describe a field and any editable O2M columns for behavior definitions."""
    try:
        field_type = application_field.get_field_type().id
    except (ValueError, AttributeError):
        field_type = application_field.field_type
    entry: dict[str, Any] = {
        "id": str(application_field.pk),
        "name": application_field.field,
        "label": application_field.title,
        "fieldType": field_type,
    }
    if field_type != "OneToManyField":
        return entry
    widget = application_field.get_widget(layout_config=layout_config)
    if not isinstance(widget, OneToManyFieldWidget):
        return entry
    entry["columns"] = [
        build_behavior_catalog_entry(column) for column in widget.get_columns()
    ]
    return entry


def behavior_option_field(application_field: "ApplicationField") -> forms.Field:
    """Build the behavior editor with its source and target field catalog."""
    return BehaviorField(**get_behavior_form_field_kwargs(application_field))


def standard_display_options(application_field: "ApplicationField") -> tuple[FieldDisplayOption, ...]:
    """Offer the common label and behavior settings for ordinary fields."""
    return (LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION)


BEHAVIORS_DISPLAY_OPTION = FieldDisplayOption(
    id="behaviors",
    label="Behaviors",
    form_factory=behavior_option_field,
    required=False,
    help_text="Define what this form should do when the field changes.",
)

