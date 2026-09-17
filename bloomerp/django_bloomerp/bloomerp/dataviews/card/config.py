from typing import Literal

from django import forms
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataview,
    page_size_choices,
)


class CardDataView(BaseDataview):
    """A declarative card dataview."""

    view_type: Literal["card"] = "card"
    page_size: Literal[10, 25, 50, 100] = 25

    @classmethod
    def create_form_field(cls, name, field_info, state):
        if name == "page_size":
            return forms.TypedChoiceField(
                **page_size_choices(state.accessible_fields),
                label=_("Page size"),
                help_text=_("The number of cards shown on each page."),
                required=False,
            )
        return super().create_form_field(name, field_info, state)
