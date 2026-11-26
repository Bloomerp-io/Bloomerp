from typing import Any

from django import forms


class BloomerpTextEditorWidget(forms.Textarea):
    template_name = "cotton/ui/inputs/text_editor.html"

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Pass editor settings through and hide the formatting toolbar in inline cells."""
        attrs = attrs or {}
        attrs.setdefault("id", f"id_{name}")
        context = super().get_context(name, value, attrs)
        widget_context = context.get("widget", {})
        widget_attrs = widget_context.get("attrs", {})
        widget_classes = widget_attrs.get("class", "").split()
        in_table_cell = "one-to-many-field-widget__input" in widget_classes
        new_context = {**widget_attrs}
        new_context.update(
            {
                "name": widget_context.get("name"),
                "application_field_id": widget_attrs.get("data-application-field-id", ""),
                "value": widget_context.get("value") or "",
                "disabled": widget_attrs.get("disabled", False),
                "compact": in_table_cell,
                "has_border": widget_attrs.get("has_border", False),
            }
        )
        if in_table_cell:
            new_context["toolbar"] = False
        return new_context
