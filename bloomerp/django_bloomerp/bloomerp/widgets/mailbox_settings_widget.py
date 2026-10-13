"""Compound presentation editor used as the value side of a mailbox mapping."""

from typing import Any
from django import forms


class MailboxSettingsWidget(forms.MultiWidget):
    """Collect a mailbox label, sent/main roles and optional color together."""

    template_name = "widgets/mailbox_settings.html"

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        """Create independently labelled inputs for each mailbox setting."""
        super().__init__(
            [
                forms.TextInput(),
                forms.CheckboxInput(),
                forms.CheckboxInput(),
                forms.HiddenInput(),
            ],
            attrs,
        )

    def get_context(
        self, name: str, value: Any, attrs: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Size controls independently and keep role checkboxes and colors optional."""
        context = super().get_context(name, value, attrs)
        for index, subwidget in enumerate(context["widget"]["subwidgets"]):
            subwidget["attrs"].pop("aria-label", None)
            if index != 0:
                subwidget["attrs"].pop("required", None)
            if index == 0:
                subwidget["attrs"]["class"] = "h-8 w-full min-w-0 rounded-lg border border-gray-200 bg-base px-2 text-sm focus:ring-1 focus:ring-primary"
                subwidget["attrs"]["data-mailbox-label"] = True
            elif index in (1, 2):
                subwidget["attrs"]["class"] = "size-4 shrink-0 rounded border-gray-300 text-primary focus:ring-primary"
                subwidget["attrs"]["data-mailbox-sent" if index == 1 else "data-mailbox-main"] = True
            else:
                subwidget["attrs"]["data-mailbox-color-value"] = True
        return context

    def decompress(self, value: Any) -> list[Any]:
        """Expand a saved mailbox mapping value in field order."""
        if isinstance(value, dict):
            return [
                value.get("label", ""),
                value.get("sent_folder", False),
                value.get("main_folder", False),
                value.get("color", ""),
            ]
        return ["", False, False, ""]
