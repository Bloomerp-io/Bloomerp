from __future__ import annotations

from typing import TYPE_CHECKING

from bloomerp.field_types.registry import FieldContext, FieldTypeDefinition, FormFactory
from django import forms

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def form(cls: type[forms.Field], *, virtual: bool = False) -> FormFactory:
    """Adapt a form class while retaining Django's model-derived arguments."""

    def build(context: FieldContext, default: forms.Field | None) -> forms.Field | None:
        application_field = context.application_field
        if application_field is None:
            if default is not None:
                return default
            # Relations and virtual editors need source-field metadata.
            if virtual or issubclass(cls, forms.ModelChoiceField):
                return None
            return cls()
        if virtual:
            from bloomerp.form_fields.one_to_many_field import OneToManyField

            kwargs = {"required": False, "label": application_field.title}
            if issubclass(cls, OneToManyField):
                kwargs["application_field"] = application_field
            return cls(**kwargs)
        model_field = application_field._get_model_field()
        if not hasattr(model_field, "formfield"):
            return default
        return model_field.formfield(form_class=cls)

    return build


def _default_form(
    application_field: ApplicationField,
    definition: FieldTypeDefinition,
    context: FieldContext,
) -> forms.Field | None:
    from django.core.exceptions import FieldDoesNotExist

    try:
        model_field = application_field._get_model_field()
    except FieldDoesNotExist:
        model_field = None

    form_field = model_field.formfield() if hasattr(model_field, "formfield") else None
    if definition.form_factory is not None:
        form_field = definition.form_factory(context, form_field)
    return form_field


def _context(
    application_field: ApplicationField, layout_config: dict | None
) -> FieldContext:
    return FieldContext(
        application_field=application_field,
        attrs={"class": "input w-full", **(application_field.meta or {})},
        layout_config=layout_config or {},
    )


def build_form_field(
    application_field: ApplicationField, *, layout_config: dict | None = None
) -> forms.Field | None:
    """Share Django defaults and virtual form factories across all form consumers."""
    definition = application_field.get_field_type()
    context = _context(application_field, layout_config)
    form_field = _default_form(application_field, definition, context)
    if form_field is None:
        return None

    if definition.widget_factory is not None:
        form_field.widget = definition.widget_factory(context)
    else:
        form_field.widget.attrs.update(context.attrs)
    return form_field


def build_widget(
    application_field: ApplicationField, *, layout_config: dict | None = None
) -> forms.Widget:
    definition = application_field.get_field_type()
    context = _context(application_field, layout_config)
    if definition.widget_factory is not None:
        return definition.widget_factory(context)

    form_field = _default_form(application_field, definition, context)
    if form_field is None:
        return forms.TextInput(attrs=context.attrs)
    form_field.widget.attrs.update(context.attrs)
    return form_field.widget
