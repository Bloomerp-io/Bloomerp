from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.forms import widgets

SKIPPED_FIELD_NAMES = {
    "created_by",
    "updated_by",
    "datetime_created",
    "datetime_updated",
}


class OneToManyFieldWidget(widgets.Widget):
    template_name = 'widgets/one_to_many_field_widget.html'
    related_model: Model = None
    parent_model: Model = None
    fields: list = []

    def __init__(self, attrs=None):
        attrs = (attrs or {}).copy()
        self.layout_config = attrs.pop('layout_config', {}) or {}
        self.related_model = attrs.pop('related_model', None)
        self.parent_model = attrs.pop('parent_model', None)
        self.fields = attrs.pop('fields', []) or self.layout_config.get("inline_fields", [])
        super().__init__(attrs)

    def _get_related_objects(self, value):
        if value is None:
            return []
        if hasattr(value, 'all'):
            return list(value.all())
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def _get_columns(self):
        if not self.related_model:
            return []

        from bloomerp.models import ApplicationField

        content_type = ContentType.objects.get_for_model(self.related_model)
        queryset = ApplicationField.objects.filter(content_type=content_type)

        if self.fields:
            fields_by_name = {
                field.field: field
                for field in queryset.filter(field__in=self.fields)
                if not self._is_parent_link_field(field) and not self._should_skip_field(field)
            }
            return [
                fields_by_name[field_name]
                for field_name in self.fields
                if field_name in fields_by_name
            ]

        columns = []
        for application_field in queryset.order_by("field"):
            if self._is_parent_link_field(application_field):
                continue
            if self._should_skip_field(application_field):
                continue
            try:
                model_field = application_field._get_model_field()
            except Exception:
                continue
            if getattr(model_field, "auto_created", False):
                continue
            if not getattr(model_field, "editable", True):
                continue
            if not getattr(model_field, "concrete", True):
                continue
            columns.append(application_field)
            if len(columns) >= 6:
                break
        return columns

    def _is_parent_link_field(self, application_field) -> bool:
        if self.parent_model is None:
            return False
        try:
            model_field = application_field._get_model_field()
        except Exception:
            return False
        remote_field = getattr(model_field, "remote_field", None)
        return getattr(remote_field, "model", None) == self.parent_model

    def _should_skip_field(self, application_field) -> bool:
        return application_field.field in SKIPPED_FIELD_NAMES

    def _render_cell_input(self, *, name, obj, application_field, attrs, row_index):
        cell_attrs = {
            "class": "one-to-many-field-widget__input input input-sm w-full border-0 bg-transparent px-2 py-1 shadow-none focus:bg-white",
        }
        if attrs and attrs.get("disabled"):
            cell_attrs["disabled"] = "disabled"
        if attrs and attrs.get("readonly"):
            cell_attrs["readonly"] = "readonly"

        value = self._get_cell_value(obj=obj, application_field=application_field)
        widget = application_field.get_widget()
        return widget.render(
            name=f"{name}__{row_index}__{application_field.field}",
            value=value,
            attrs=cell_attrs,
        )

    def _get_cell_value(self, *, obj, application_field):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(application_field.field)
        return getattr(obj, application_field.field, None)

    def _build_cells(self, *, name, obj, columns, attrs, row_index):
        return [
            {
                "column": column,
                "input": self._render_cell_input(
                    obj=obj,
                    application_field=column,
                    attrs=attrs,
                    name=name,
                    row_index=row_index,
                ),
            }
            for column in columns
        ]
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        attrs = attrs or {}
        context['widget']['attrs']['name'] = name
        
        # Get content type ID for the related model
        if self.related_model:
            context['content_type_id'] = ContentType.objects.get_for_model(self.related_model).id
        else:
            context['content_type_id'] = None
        
        columns = self._get_columns()
        related_objects = self._get_related_objects(value)
        rows = []
        for row_index, obj in enumerate(related_objects):
            rows.append(
                {
                    "object": obj,
                    "id_input": self._render_row_id_input(name=name, obj=obj, row_index=row_index),
                    "cells": self._build_cells(
                        name=name,
                        obj=obj,
                        columns=columns,
                        attrs=attrs,
                        row_index=row_index,
                    ),
                }
            )

        context['related_objects'] = related_objects
        context['columns'] = columns
        context['rows'] = rows
        context['empty_row'] = {
            "id_input": self._render_row_id_input(name=name, obj=None, row_index="__prefix__"),
            "cells": self._build_cells(
                name=name,
                obj=None,
                columns=columns,
                attrs=attrs,
                row_index="__prefix__",
            ),
        }
        context['can_edit'] = not attrs.get("disabled")
        
        return context

    def _render_row_id_input(self, *, name, obj, row_index):
        value = getattr(obj, "pk", "") if obj is not None else ""
        return widgets.HiddenInput().render(
            name=f"{name}__{row_index}__id",
            value=value,
        )
