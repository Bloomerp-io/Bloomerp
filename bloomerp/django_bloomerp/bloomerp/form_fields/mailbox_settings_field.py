"""Typed compound value for configuring an individual provider mailbox."""

from typing import Any
from django import forms
from bloomerp.widgets.mailbox_settings_widget import MailboxSettingsWidget


class MailboxSettingsField(forms.MultiValueField):
    """Clean a label, two role toggles and an optional hexadecimal color."""

    def __init__(self, **kwargs: Any) -> None:
        """Compose fields with independent required checks for the mailbox editor."""
        super().__init__(
            fields=[
                forms.CharField(max_length=255),
                forms.BooleanField(required=False),
                forms.BooleanField(required=False),
                forms.RegexField(r"^#[0-9a-fA-F]{6}$", required=False),
            ],
            require_all_fields=False,
            widget=MailboxSettingsWidget(),
            **kwargs,
        )

    def clean(self, value: Any) -> dict[str, Any]:
        """Accept both browser input lists and saved mapping dictionaries."""
        if isinstance(value, dict):
            value = self.widget.decompress(value)
        return super().clean(value)

    def compress(self, data_list: list[Any]) -> dict[str, Any]:
        """Return the JSON-compatible mailbox settings object."""
        if not data_list:
            return {}
        return dict(zip(("label", "sent_folder", "main_folder", "color"), data_list))
