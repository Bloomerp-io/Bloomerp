from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db import models
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataview,
    application_field_choices,
)

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class CalendarViewMode(models.TextChoices):
    DAY = "day", _("Day")
    WEEK = "week", _("Week")
    MONTH = "month", _("Month")
    YEAR = "year", _("Year")
    LIST = "list", _("List")


class CalendarDataView(BaseDataview):
    """A declarative calendar dataview."""

    view_type: Literal["calendar"] = "calendar"
    start_field: str | None = None
    end_field: str | None = None
    view_mode: Literal["day", "week", "month", "year", "list"] = "week"
    color_grouping_field: str | None = None
    application_field_options = {
        "start_field": "single",
        "end_field": "single",
        "color_grouping_field": "single",
    }

    @classmethod
    def create_form_field(cls, name, field_info, state):
        application_fields = state.accessible_fields
        field_options = {
            "start_field": (
                forms.TypedChoiceField,
                {
                    **date_field_choices(application_fields),
                    "label": _("Date field"),
                    "help_text": _("The date field used to place records on the calendar."),
                },
            ),
            "end_field": (
                forms.TypedChoiceField,
                {
                    **date_field_choices(application_fields),
                    "label": _("End date field"),
                    "help_text": _("Optional date field used as the end of an event range."),
                },
            ),
            "view_mode": (
                forms.ChoiceField,
                {
                    **view_mode_choices(application_fields),
                    "label": _("View mode"),
                    "help_text": _("The calendar period to show."),
                },
            ),
            "color_grouping_field": (
                forms.TypedChoiceField,
                {
                    **calendar_color_field_choices(application_fields),
                    "label": _("Color grouping"),
                    "help_text": _("Optional field used to color calendar items and build the legend."),
                },
            ),
        }
        field_definition = field_options.get(name)
        if field_definition is None:
            return super().create_form_field(name, field_info, state)
        field_cls, kwargs = field_definition
        return field_cls(required=False, **kwargs)


def date_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("Select a date field"),
            field_types={"DateField", "DateTimeField"},
        ),
        "coerce": lambda value: value or None,
        "empty_value": None,
    }


def view_mode_choices(
    _application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {"choices": CalendarViewMode.choices}


def calendar_color_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("No color grouping"),
        ),
        "coerce": lambda value: value or None,
        "empty_value": None,
    }
