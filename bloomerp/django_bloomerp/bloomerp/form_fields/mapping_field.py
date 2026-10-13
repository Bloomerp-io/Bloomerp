"""Reusable typed key/value mappings for configuration forms."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from bloomerp.widgets.mapping_widget import MappingWidget


class MappingField(forms.Field):
    """Clean editable mapping rows with independently configured key/value fields."""

    def __init__(
        self,
        left: Iterable[tuple[Any, str]] | None = None,
        right: Iterable[tuple[Any, str]] | None = None,
        *,
        left_field: forms.Field | None = None,
        right_field: forms.Field | None = None,
        left_widget: forms.Widget | None = None,
        right_widget: forms.Widget | None = None,
        allow_adding_groups: bool | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure optional choices, typed fields, widgets and row creation."""
        left = list(left) if left is not None else None
        right = list(right) if right is not None else None
        self.left_field = left_field or (
            forms.ChoiceField(choices=left) if left is not None else forms.CharField()
        )
        self.right_field = right_field or (
            forms.ChoiceField(choices=[("", _("Choose value")), *right])
            if right is not None
            else forms.CharField()
        )
        if left_widget is not None:
            self.left_field.widget = left_widget
        if right_widget is not None:
            self.right_field.widget = right_widget
        self.allow_adding_groups = (
            left is None if allow_adding_groups is None else allow_adding_groups
        )
        self.left = list(left) if left is not None else None
        kwargs.setdefault(
            "widget",
            MappingWidget(
                left_widget=self.left_field.widget,
                right_widget=self.right_field.widget,
                left=self.left,
                allow_adding_groups=self.allow_adding_groups,
            ),
        )
        super().__init__(**kwargs)

    def to_python(self, value: Any) -> dict[str, Any]:
        """Validate each pair, rejecting incomplete rows and duplicate cleaned keys."""
        if value in self.empty_values:
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("Enter a valid mapping.")) from exc
        if isinstance(value, dict):
            value = list(value.items())
        if not isinstance(value, (list, tuple)):
            raise ValidationError(_("Enter a valid mapping."))
        result: dict[str, Any] = {}
        for row in value:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValidationError(_("Enter a valid mapping row."))
            key, item = row
            if key in self.empty_values and item in self.empty_values:
                continue
            if not self.allow_adding_groups and item in self.empty_values:
                continue
            key = str(self.left_field.clean(key))
            if (
                self.left is not None
                and not self.allow_adding_groups
                and key not in {str(item[0]) for item in self.left}
            ):
                raise ValidationError(_("Choose a configured mapping key."))
            item = self.right_field.clean(item)
            if key in result:
                raise ValidationError(_("Each mapping key must be unique."))
            result[key] = item
        return result
