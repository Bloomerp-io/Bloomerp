from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms

from bloomerp.field_types.registry import FieldContext, FormFactory, WidgetFactory

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


def form(
    cls: type[forms.Field],
    *,
    virtual: bool = False,
    disabled: bool = False,
) -> FormFactory:
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

            kwargs = {
                "required": False,
                "disabled": disabled,
                "label": application_field.title,
            }
            if issubclass(cls, OneToManyField):
                kwargs["application_field"] = application_field
            return cls(**kwargs)
        model_field = application_field._get_model_field()
        if not hasattr(model_field, "formfield"):
            return default
        return model_field.formfield(form_class=cls)

    return build


def _resolve_factories(
    application_field: ApplicationField,
) -> tuple[FormFactory | None, WidgetFactory | None]:
    """Resolve each factory from field settings or the registered field type."""
    definition = application_field.get_field_type()
    setting = application_field.get_field_setting()
    if setting is None:
        return definition.form_factory, definition.widget_factory

    form_factory = setting.form_factory
    widget_factory = setting.widget_factory
    return (
        form_factory if form_factory is not None else definition.form_factory,
        widget_factory if widget_factory is not None else definition.widget_factory,
    )


def _default_form(
    application_field: ApplicationField,
    form_factory: FormFactory | None,
    context: FieldContext,
) -> forms.Field | None:
    """Build Django's default form field and pass it to the resolved factory."""
    from django.core.exceptions import FieldDoesNotExist

    try:
        model_field = application_field._get_model_field()
    except FieldDoesNotExist:
        model_field = None

    form_field = model_field.formfield() if hasattr(model_field, "formfield") else None
    if form_factory is not None:
        form_field = form_factory(context, form_field)
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
    """Build a form field and apply its resolved widget factory, if available."""
    form_factory, widget_factory = _resolve_factories(application_field)
    context = _context(application_field, layout_config)
    form_field = _default_form(application_field, form_factory, context)
    if form_field is None:
        return None

    if widget_factory is not None:
        form_field.widget = widget_factory(context)
    else:
        form_field.widget.attrs.update(context.attrs)
    return form_field


def build_widget(
    application_field: ApplicationField, *, layout_config: dict | None = None
) -> forms.Widget:
    """Build the resolved widget or use the widget from the resolved form field."""
    form_factory, widget_factory = _resolve_factories(application_field)
    context = _context(application_field, layout_config)
    if widget_factory is not None:
        return widget_factory(context)

    form_field = _default_form(application_field, form_factory, context)
    if form_field is None:
        return forms.TextInput(attrs=context.attrs)
    form_field.widget.attrs.update(context.attrs)
    return form_field.widget
