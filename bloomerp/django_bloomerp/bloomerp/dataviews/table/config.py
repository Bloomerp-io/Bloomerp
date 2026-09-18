from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataview,
    PageSize,
    application_field_name_choices,
    page_size_choices,
)

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class TableDataView(BaseDataview):
    """A declarative table dataview."""

    view_type: Literal["table"] = "table"
    page_size: Literal[10, 25, 50, 100] = 25
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "asc"

    @classmethod
    def create_form_field(cls, name, field_info, state):
        application_fields = state.accessible_fields
        field_options = {
            "page_size": (
                forms.TypedChoiceField,
                {
                    **page_size_choices(application_fields),
                    "label": _("Page size"),
                    "help_text": _("The number of records shown on each page."),
                },
            ),
            "sort_field": (
                forms.TypedChoiceField,
                {
                    **sort_field_choices(application_fields),
                    "label": _("Sort on"),
                    "help_text": _("The field used for table sorting."),
                },
            ),
            "sort_direction": (
                forms.ChoiceField,
                {
                    **sort_direction_choices(application_fields),
                    "label": _("Sort direction"),
                    "help_text": _("The direction used for table sorting."),
                },
            ),
        }
        field_definition = field_options.get(name)
        if field_definition is None:
            return super().create_form_field(name, field_info, state)
        field_cls, kwargs = field_definition
        return field_cls(required=False, **kwargs)


def sort_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": application_field_name_choices(
            application_fields,
            include_empty=True,
            empty_label=_("Default"),
        ),
        "coerce": lambda value: value or None,
        "empty_value": None,
    }


def sort_direction_choices(
    _application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": [
            ("asc", _("Ascending")),
            ("desc", _("Descending")),
        ]
    }
