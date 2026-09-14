

import json
from typing import Any

from django import forms
from django.contrib.contenttypes.models import ContentType


class FilterWidget(forms.Widget):
    """Django widget adapter for the unified grouped-filter editor."""

    template_name = "widgets/filter_widget.html"

    def __init__(
        self,
        model=None,
        attrs=None,
        *,
        content_type: ContentType | None = None,
        include_controls: bool = True,
    ):
        if model is not None and content_type is not None:
            raise TypeError("Pass either model or content_type, not both.")

        if isinstance(model, ContentType):
            content_type = model
            model = None

        self.model = model
        self.content_type = content_type
        self.include_controls = include_controls
        super().__init__(attrs)

    @property
    def content_type_id(self) -> int | None:
        """Return the model's ContentType primary key for the filter scope."""
        if self.content_type is not None:
            return self.content_type.pk
        if self.model is None:
            return None
        return ContentType.objects.get_for_model(self.model).pk

    def format_value(self, value: Any) -> str:
        """Return a JSON payload safe for the unified container attribute."""
        if value in (None, "", []):
            return "[]"

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                # Keep malformed JSON visible to the unified container, which
                # reports its existing restore error without executing it.
                return value
        else:
            parsed = value

        if not isinstance(parsed, list):
            return "[]"
        return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)

    def value_from_datadict(self, data, files, name):
        """Read the hidden JSON value emitted by the frontend container."""
        return data.get(name)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update(
            {
                "content_type_id": self.content_type_id or "",
                "initial_filters": self.format_value(value),
                "field_attrs": context["widget"]["attrs"],
                "include_controls": self.include_controls,
            }
        )
        return context
