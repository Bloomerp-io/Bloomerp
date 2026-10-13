from collections.abc import Mapping
from typing import Any

from django import forms

from bloomerp.field_types.registry import FieldContext, WidgetFactory


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
    """Build inline columns using explicit preferences or the model's default ordering."""
    from bloomerp.models.definition import get_model_config
    from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget

    application_field = context.application_field
    layout_config = dict(context.layout_config)
    if application_field is not None and "inline_fields" not in layout_config:
        model_config = get_model_config(application_field.get_model())
        detail_settings = model_config.detail_view_settings if model_config else None
        default_layout = detail_settings.get_default_layout() if detail_settings else None
        if default_layout is not None:
            for row in default_layout.rows:
                for item in row.items:
                    if (
                        str(item.id) in {application_field.field, str(application_field.pk)}
                        and "inline_fields" in item.config
                    ):
                        layout_config["inline_fields"] = item.config["inline_fields"]
    return OneToManyFieldWidget(
        attrs={
            **context.attrs,
            "related_model": (
                application_field.get_related_model() if application_field else None
            ),
            "parent_model": (
                application_field.get_model() if application_field else None
            ),
            "layout_config": layout_config,
        }
    )


def relation_widget(*, multiple: bool = False) -> WidgetFactory:
    """Build relation widgets with the metadata defining their allowed choices."""

    def build(context: FieldContext) -> forms.Widget:
        """Pass the related model and source application field to the widget."""
        from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

        application_field = context.application_field
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
