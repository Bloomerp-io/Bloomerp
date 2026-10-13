"""Native choice selects with validated per-choice color accents."""

from __future__ import annotations

import re
from typing import Any

from django import forms


class ColoredChoicesWidget(forms.Select):
    """Keep standard select submission while exposing colors to the UI component."""

    template_name = "widgets/colored_choices_widget.html"

    def __init__(
        self,
        attrs: dict[str, Any] | None = None,
        choices: Any = (),
        *,
        colors: Any = None,
    ) -> None:
        """Retain only six-digit hex colors and keep widget state instance-local."""
        self.colors = {
            str(key): color
            for key, color in (colors.items() if isinstance(colors, dict) else [])
            if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
        }
        super().__init__(
            {**(attrs or {}), "bloomerp-component": "colored-choices"}, choices
        )

    def create_option(
        self,
        name: str,
        value: Any,
        label: Any,
        selected: bool,
        index: int,
        subindex: int | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach safe colors to matching options, ignoring removed choice mappings."""
        option = super().create_option(
            name, value, label, selected, index, subindex, attrs
        )
        color = self.colors.get(str(value))
        if color:
            option["attrs"]["data-choice-color"] = color
            option["attrs"]["style"] = f"border-left: 6px solid {color}"
        return option

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Render the current color before JavaScript initializes the select."""
        context = super().get_context(name, value, attrs)
        selected = {
            str(option["value"])
            for _group, options, _index in context["widget"]["optgroups"]
            for option in options
            if option["selected"]
        }
        color = next((self.colors[key] for key in selected if key in self.colors), None)
        if color:
            current_style = context["widget"]["attrs"].get("style", "")
            context["widget"]["attrs"]["style"] = (
                f"{current_style};border-left: 6px solid {color}"
            )
        return context
