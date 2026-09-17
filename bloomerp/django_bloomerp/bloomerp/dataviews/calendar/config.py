from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db import models
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataView,
    PreferenceOption,
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


class CalendarDataView(BaseDataView):
    """A declarative calendar dataview."""

    view_type: Literal["calendar"] = "calendar"
    start_field: str | None = None
    end_field: str | None = None
    view_mode: Literal["day", "week", "month", "year", "list"] = "week"
    color_grouping_field: str | None = None


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
        "coerce": int,
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
        "coerce": int,
        "empty_value": None,
    }


CALENDAR_OPTIONS = [
    PreferenceOption(
        key="start_field_id",
        label=_("Date field"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=date_field_choices,
        description=_("The date field used to place records on the calendar."),
        data_type=int | None,
        default_value=None,
    ),
    PreferenceOption(
        key="end_field_id",
        label=_("End date field"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=date_field_choices,
        description=_("Optional date field used as the end of an event range."),
        data_type=int | None,
        default_value=None,
    ),
    PreferenceOption(
        key="view_mode",
        label=_("View mode"),
        field_cls=forms.ChoiceField,
        field_attrs_func=view_mode_choices,
        description=_("The calendar period to show."),
        data_type=str,
        default_value=CalendarViewMode.WEEK,
    ),
    PreferenceOption(
        key="color_grouping_field_id",
        label=_("Color grouping"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=calendar_color_field_choices,
        description=_(
            "Optional field used to color calendar items and build the legend."
        ),
        data_type=int | None,
        default_value=None,
    ),
]
