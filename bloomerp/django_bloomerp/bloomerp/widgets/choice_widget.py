"""Searchable single and multiple choices with native select submission."""

from typing import Any

from django import forms


class ChoiceWidget(forms.Select):
    """Display static choices as searchable, removable selections inside a field."""

    template_name = "widgets/choice_widget.html"

    def __init__(
        self,
        attrs: dict[str, Any] | None = None,
        choices: Any = (),
        *,
        allow_multiple: bool = False,
    ) -> None:
        """Configure native multiple selection without mutating supplied attributes."""
        attrs = (attrs or {}).copy()
        self.allow_multiple_selected = bool(attrs.pop("allow_multiple", allow_multiple))
        super().__init__(attrs=attrs, choices=choices)
