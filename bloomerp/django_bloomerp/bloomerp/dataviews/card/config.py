from typing import Literal

from django import forms
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataView,
    PageSize,
    PreferenceOption,
    page_size_choices,
)


class CardDataView(BaseDataView):
    """A declarative card dataview."""

    view_type: Literal["card"] = "card"
    page_size: Literal[10, 25, 50, 100] = 25


CARD_OPTIONS = [
    PreferenceOption(
        key="page_size",
        label=_("Page size"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=page_size_choices,
        description=_("The number of cards shown on each page."),
        data_type=int,
        default_value=PageSize.SIZE_25,
    ),
]
