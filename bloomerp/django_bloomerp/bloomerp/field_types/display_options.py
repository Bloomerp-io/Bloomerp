"""Application-field-aware factories for layout display settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from django import forms
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField


@dataclass
class FieldDisplayOption:
    """Describe a setting and supply common metadata to its fresh form field.

    Factory labels and help text override option metadata when nonempty.
    Set required=None to retain the factory's required setting.
    """

    id: str
    label: str
    form_factory: Callable[[ApplicationField], forms.Field]
    required: bool | None = False
    default: Any = None
    help_text: str = ""

    def build_form_field(self, application_field: ApplicationField) -> forms.Field:
        """Build a field and fill metadata without repeating it in each factory."""
        form_field = self.form_factory(application_field)
        if form_field.label is None:
            form_field.label = self.label
        if not form_field.help_text:
            form_field.help_text = self.help_text
        if self.required is not None:
            form_field.required = self.required
            form_field.widget.is_required = self.required
        return form_field


def text_option_field(application_field: ApplicationField) -> forms.Field:
    """Create a plain text editor for a display setting."""
    return forms.CharField()


LABEL_OPTION = FieldDisplayOption(
    id="label",
    label=_("Label"),
    form_factory=text_option_field,
)

HELP_TEXT_FIELD_OPTION = FieldDisplayOption(
    id="help_text",
    label=_("Help Text"),
    form_factory=text_option_field,
    help_text=_("This text will be displayed below the field in the form."),
)
