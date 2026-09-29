from bloomerp.field_types.registry import FieldContext, WidgetFactory


from django import forms


from collections.abc import Mapping
from typing import Any


def widget(
    cls: type[forms.Widget],
    *,
    attrs: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> WidgetFactory:
    """Helper function to build a widget

    Args:
        cls (type[forms.Widget]): the widget cls
        attrs (Mapping[str, Any] | None, optional): Optional attrs. Defaults to None.

    Returns:
        WidgetFactory: the widget factory
    """

    def build(context: FieldContext) -> forms.Widget:
        return cls(attrs={**(attrs or {}), **context.attrs}, **kwargs)

    return build


def inline_widget(context: FieldContext) -> forms.Widget:
    from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget

    application_field = context.application_field
    return OneToManyFieldWidget(
        attrs={
            **context.attrs,
            "related_model": (
                application_field.get_related_model() if application_field else None
            ),
            "parent_model": (
                application_field.get_model() if application_field else None
            ),
            "layout_config": dict(context.layout_config),
        }
    )


def relation_widget(*, multiple: bool = False) -> WidgetFactory:
    """Build relation widgets with the metadata defining their allowed choices."""

    def build(context: FieldContext) -> forms.Widget:
        """Pass the related model and source application field to the widget."""
        from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

        application_field = context.application_field
        if application_field is not None:
            model_field = application_field._get_model_field()
            if (
                not multiple
                and (model_field.many_to_one or model_field.one_to_one)
                and not model_field.target_field.primary_key
            ):
                form_field = model_field.formfield()
                if form_field is not None:
                    form_field.widget.attrs.update(context.attrs)
                    return form_field.widget

        return ForeignFieldWidget(
            attrs={
                "is_m2m": multiple,
                **context.attrs,
                "model": (
                    application_field.get_related_model() if application_field else None
                ),
                "source_field": application_field,
            }
        )

    return build
