import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Model
from django.forms import widgets
from django.urls import reverse

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField

SKIPPED_FIELD_NAMES = {
    "created_by",
    "updated_by",
    "datetime_created",
    "datetime_updated",
}
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


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
        self.page_size = self._parse_page_size(self.layout_config.get("page_size"))
        super().__init__(attrs)

    @staticmethod
    def _parse_page_size(value) -> int:
        """Return a bounded page size from layout configuration."""
        try:
            page_size = int(value)
        except (TypeError, ValueError):
            return DEFAULT_PAGE_SIZE
        return min(MAX_PAGE_SIZE, max(1, page_size))

    def _get_related_objects(self, value):
        if value is None:
            return []
        if hasattr(value, 'all'):
            return list(value.all())
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def get_columns(self):
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

    # Backwards-compatible alias for callers that used the former private API.
    _get_columns = get_columns

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

    def _render_cell_input(
        self,
        *,
        name,
        obj,
        application_field,
        attrs,
        row_index,
        default_values=None,
    ):
        widget = application_field.get_widget()
        if isinstance(widget, widgets.CheckboxInput):
            input_classes = (
                "one-to-many-field-widget__input h-5 w-5 cursor-pointer rounded "
                "border-gray-400 text-primary focus:ring-primary"
            )
        else:
            input_classes = (
                "one-to-many-field-widget__input input input-sm w-full border-0 "
                "bg-transparent px-2 py-1 shadow-none focus:bg-white"
            )
        cell_attrs = {"class": input_classes}
        if attrs and attrs.get("disabled"):
            cell_attrs["disabled"] = "disabled"
        if attrs and attrs.get("readonly"):
            cell_attrs["readonly"] = "readonly"

        value = self._get_cell_value(
            obj=obj,
            application_field=application_field,
            default_values=default_values,
        )
        return widget.render(
            name=f"{name}__{row_index}__{application_field.field}",
            value=value,
            attrs=cell_attrs,
        )

    def _get_cell_value(self, *, obj, application_field, default_values=None):
        if obj is None:
            return (default_values or {}).get(application_field.field)
        if isinstance(obj, dict):
            if application_field.field in obj:
                return obj[application_field.field]
            return (default_values or {}).get(application_field.field)
        return getattr(obj, application_field.field, None)

    def _build_cells(self, *, name, obj, columns, attrs, row_index, default_values=None):
        return [
            {
                "column": column,
                "input": self._render_cell_input(
                    obj=obj,
                    application_field=column,
                    attrs=attrs,
                    name=name,
                    row_index=row_index,
                    default_values=default_values,
                ),
            }
            for column in columns
        ]

    @staticmethod
    def _get_column_kind(application_field: "ApplicationField") -> str:
        """Return the client-side behavior category for an inline column."""
        try:
            model_field = application_field._get_model_field()
        except Exception:
            return "text"

        if isinstance(model_field, models.BooleanField):
            return "boolean"
        if isinstance(model_field, models.DateField):
            return "date"
        if isinstance(
            model_field,
            (models.IntegerField, models.FloatField, models.DecimalField),
        ):
            return "number"
        return "text"

    def _build_column_context(
        self,
        application_field: "ApplicationField",
        *,
        has_default: bool,
        default_value: object = None,
    ) -> dict[str, object]:
        """Build the metadata used by column actions, totals, and cell selectors."""
        kind = self._get_column_kind(application_field)
        return {
            "id": application_field.pk,
            "field": application_field.field,
            "title": application_field.title,
            "kind": kind,
            "show_total": bool(self.layout_config.get("show_totals")) and kind == "number",
            "default_value_json": (
                self._serialize_default_value(default_value) if has_default else ""
            ),
        }

    @staticmethod
    def _get_column_default(application_field: "ApplicationField") -> tuple[bool, object]:
        """Return a related model field's default in widget-ready form."""
        try:
            model_field = application_field._get_model_field()
        except Exception:
            return False, None
        if not model_field.has_default():
            return False, None

        try:
            default_value = model_field.get_default()
            form_field = application_field.get_form_field()
            if form_field is not None:
                default_value = form_field.prepare_value(default_value)
            return True, default_value
        except Exception:
            return True, None

    @staticmethod
    def _serialize_default_value(value: object) -> str:
        """Serialize a column default for the frontend data attribute."""
        try:
            return json.dumps(value, cls=DjangoJSONEncoder)
        except (TypeError, ValueError):
            return json.dumps(str(value))
    
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        attrs = attrs or {}
        context['widget']['attrs']['name'] = name
        
        # Get content type ID for the related model
        if self.related_model:
            context['content_type_id'] = ContentType.objects.get_for_model(self.related_model).id
            context['detail_url_template'] = self._get_detail_url_template()
        else:
            context['content_type_id'] = None
            context['detail_url_template'] = ""
        
        columns = self.get_columns()
        column_defaults = {}
        column_context = []
        for column in columns:
            has_default, default_value = self._get_column_default(column)
            if has_default:
                column_defaults[column.field] = default_value
            column_context.append(
                self._build_column_context(
                    column,
                    has_default=has_default,
                    default_value=default_value,
                )
            )

        related_objects = self._get_related_objects(value)
        rows = []
        for row_index, obj in enumerate(related_objects):
            rows.append(
                {
                    "object": obj,
                    "id": self._get_row_id(obj),
                    "detail_url": self._get_row_detail_url(obj),
                    "id_input": self._render_row_id_input(name=name, obj=obj, row_index=row_index),
                    "cells": self._build_cells(
                        name=name,
                        obj=obj,
                        columns=columns,
                        attrs=attrs,
                        row_index=row_index,
                        default_values=column_defaults,
                    ),
                }
            )

        context['related_objects'] = related_objects
        context['columns'] = column_context
        context['rows'] = rows
        context['empty_row'] = {
            "id": "",
            "detail_url": "",
            "id_input": self._render_row_id_input(name=name, obj=None, row_index="__prefix__"),
            "cells": self._build_cells(
                name=name,
                obj=None,
                columns=columns,
                attrs=attrs,
                row_index="__prefix__",
                default_values=column_defaults,
            ),
        }
        context['can_edit'] = not attrs.get("disabled")
        context['show_totals'] = bool(self.layout_config.get("show_totals"))
        context['page_size'] = self.page_size
        
        return context

    @staticmethod
    def _get_row_id(obj):
        if isinstance(obj, dict):
            return obj.get("id", "")
        return getattr(obj, "pk", "") if obj is not None else ""

    def _get_row_detail_url(self, obj) -> str:
        row_id = self._get_row_id(obj)
        if row_id in (None, ""):
            return ""

        if not isinstance(obj, dict) and hasattr(obj, "get_absolute_url"):
            try:
                return obj.get_absolute_url()
            except Exception:
                pass

        return self._get_detail_url_template().replace("{object_id}", str(row_id))

    def _get_detail_url_template(self) -> str:
        if self.related_model is None:
            return ""

        placeholder = UUID(int=0)
        try:
            from bloomerp.utils.models import get_detail_view_url

            detail_url = reverse(
                get_detail_view_url(self.related_model),
                kwargs={"pk": placeholder},
            )
        except Exception:
            return ""
        return detail_url.replace(str(placeholder), "{object_id}")

    def _render_row_id_input(self, *, name, obj, row_index):
        if isinstance(obj, dict):
            value = obj.get("id", "")
        else:
            value = getattr(obj, "pk", "") if obj is not None else ""
        return widgets.HiddenInput().render(
            name=f"{name}__{row_index}__id",
            value=value,
        )

    def value_from_datadict(self, data, files, name):
        rows: dict[str, dict[str, object]] = {}
        prefix = f"{name}__"

        for source in (data, files):
            for key in source.keys():
                if not key.startswith(prefix):
                    continue
                parts = key.split("__", 2)
                if len(parts) != 3:
                    continue
                _, row_index, field_name = parts
                rows.setdefault(row_index, {})[field_name] = self._submitted_value(source, key)

        return [
            row
            for _, row in sorted(rows.items(), key=lambda item: self._row_sort_key(item[0]))
        ]

    @staticmethod
    def _submitted_value(source: Mapping[str, Any], key: str) -> object:
        """Return one nested value while discarding a stale empty-value sentinel."""
        if hasattr(source, "getlist"):
            values = source.getlist(key)
            if len(values) > 1:
                non_empty_values = [
                    value for value in values if value not in (None, "")
                ]
                if len(non_empty_values) == 1:
                    return non_empty_values[0]
                if non_empty_values:
                    return non_empty_values
                return ""
        return source.get(key)

    @staticmethod
    def _row_sort_key(row_index: str):
        if row_index.isdigit():
            return (0, int(row_index))
        return (1, row_index)
