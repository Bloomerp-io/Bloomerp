from typing import Any

from django import forms


class URLWidget(forms.URLInput):
    """Keep an editable URL input with an adjacent action to open its live value."""

    template_name = "widgets/url_widget.html"

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Preserve native input attributes and reserve room for the view button."""
        context = super().get_context(name, value, attrs)
        input_attrs = context["widget"]["attrs"]
        classes = input_attrs.get("class", "input w-full").split()
        if "pr-10!" not in classes:
            classes.append("pr-10!")
        input_attrs["class"] = " ".join(classes)
        return context
