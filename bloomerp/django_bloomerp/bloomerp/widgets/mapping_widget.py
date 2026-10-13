"""Composable row editor for mapping form fields."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _


class MappingSelectMultipleWidget(forms.SelectMultiple):
    """Present multiple values in a compact disclosure containing labelled checkboxes."""

    template_name = "widgets/mapping_multiple.html"

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Expose selected labels while preserving Django's multi-value extraction."""
        context = super().get_context(name, value, attrs)
        context["widget"]["selected_labels"] = [
            str(option["label"])
            for _label, options, _index in context["widget"]["optgroups"]
            for option in options
            if option["selected"]
        ]
        return context


class MappingWidget(forms.Widget):
    """Render arbitrary Django widgets on either side of an editable mapping."""

    template_name = "widgets/mapping_widget.html"

    def __init__(
        self,
        attrs: dict[str, Any] | None = None,
        *,
        left_widget: forms.Widget | None = None,
        right_widget: forms.Widget | None = None,
        left: list[tuple[Any, str]] | None = None,
        allow_adding_groups: bool = True,
    ) -> None:
        """Keep per-instance child widgets and optional fixed left-side rows."""
        super().__init__(attrs)
        self.left_widget = deepcopy(left_widget or forms.TextInput())
        self.right_widget = deepcopy(right_widget or forms.TextInput())
        if type(self.right_widget) is forms.SelectMultiple:
            self.right_widget = MappingSelectMultipleWidget(
                attrs=self.right_widget.attrs,
                choices=self.right_widget.choices,
            )
        self.left = left
        self.allow_adding_groups = allow_adding_groups

    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        """Extract indexed pairs using each child widget's own extraction contract."""
        if name in data:
            return data.get(name)
        indices = (
            data.getlist(f"{name}__rows")
            if hasattr(data, "getlist")
            else data.get(f"{name}__rows", [])
        )
        return [
            (
                self.left_widget.value_from_datadict(
                    data, files, f"{name}__key_{index}"
                ),
                self.right_widget.value_from_datadict(
                    data, files, f"{name}__value_{index}"
                ),
            )
            for index in indices
        ]

    def value_omitted_from_data(self, data: Any, files: Any, name: str) -> bool:
        """Recognize an explicitly submitted empty mapping editor."""
        return name not in data and f"{name}__present" not in data

    def _row(
        self, name: str, index: str, key: Any, value: Any, attrs: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Render uniquely named child inputs for one mapping row."""
        child_attrs = {
            **attrs,
            "class": "w-full min-w-0 rounded-lg border border-gray-200 bg-base px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary",
        }
        base_id = attrs.get("id", name)
        return {
            "index": index,
            "left": self.left_widget.render(
                f"{name}__key_{index}",
                key,
                {
                    **child_attrs,
                    "id": f"{base_id}__key_{index}",
                    "aria-label": _("Mapping key"),
                },
            ),
            "right": self.right_widget.render(
                f"{name}__value_{index}",
                value,
                {
                    **child_attrs,
                    "id": f"{base_id}__value_{index}",
                    "aria-label": _("Mapping value"),
                },
            ),
        }

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Supply saved rows, fixed keys and an inert template for adding rows."""
        context = super().get_context(name, value, attrs)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = None
        pairs = (
            list(value.items())
            if isinstance(value, dict)
            else list(value)
            if isinstance(value, (list, tuple))
            else []
        )
        pairs = [
            row for row in pairs if isinstance(row, (tuple, list)) and len(row) == 2
        ]
        if not self.allow_adding_groups and self.left is not None:
            saved = dict(pairs)
            pairs = [
                (key, saved.get(str(key), saved.get(key))) for key, _label in self.left
            ]
        widget_attrs = context["widget"]["attrs"]
        context["widget"].update(
            {
                "rows": [
                    self._row(name, str(index), key, item, widget_attrs)
                    for index, (key, item) in enumerate(pairs)
                ],
                "empty_row": self._row(name, "__prefix__", None, None, widget_attrs),
                "allow_adding_groups": self.allow_adding_groups,
            }
        )
        return context
