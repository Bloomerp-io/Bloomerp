from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from pydantic import Field

from bloomerp.dataviews.definition import (
    BaseDataview,
    application_field_choices,
    page_size_choices,
)

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class PivotTableDataView(BaseDataview):
    """A declarative pivot-table dataview."""

    view_type: Literal["pivot_table"] = "pivot_table"
    row_fields: list[str] = Field(default_factory=list)
    column_fields: list[str] = Field(default_factory=list)
    value_fields: list[str] = Field(default_factory=list)
    aggregation: Literal["count", "sum", "min", "max", "avg"] = "count"
    show_row_totals: bool = True
    show_column_totals: bool = True
    totals_scope: Literal["page", "dataset"] = "page"
    page_size: Literal[10, 25, 50, 100] = 25
    application_field_options = {
        "row_fields": "multiple",
        "column_fields": "multiple",
        "value_fields": "multiple",
    }

    @classmethod
    def create_form_field(cls, name, field_info, state):
        application_fields = state.accessible_fields
        field_options = {
            "row_fields": (
                forms.MultipleChoiceField,
                {
                    **application_field_multiple_choices(application_fields),
                    "label": _("Rows"),
                    "help_text": _("Fields used to build the expandable row hierarchy."),
                },
            ),
            "column_fields": (
                forms.MultipleChoiceField,
                {
                    **application_field_multiple_choices(application_fields),
                    "label": _("Columns"),
                    "help_text": _("Fields used to build nested column headers."),
                },
            ),
            "value_fields": (
                forms.MultipleChoiceField,
                {
                    **application_field_multiple_choices(application_fields),
                    "label": _("Values"),
                    "help_text": _("Fields aggregated into the leaf columns of the pivot table."),
                },
            ),
            "aggregation": (
                forms.ChoiceField,
                {
                    **pivot_aggregation_choices(application_fields),
                    "label": _("Aggregation"),
                    "help_text": _("Numeric fields support all aggregations; booleans support sum and count; other fields use count."),
                },
            ),
            "show_row_totals": (
                forms.BooleanField,
                {
                    "label": _("Show row totals"),
                    "help_text": _("Add a total column for each row."),
                },
            ),
            "show_column_totals": (
                forms.BooleanField,
                {
                    "label": _("Show column totals"),
                    "help_text": _("Add a totals row beneath the pivot table."),
                },
            ),
            "totals_scope": (
                forms.ChoiceField,
                {
                    **pivot_totals_scope_choices(application_fields),
                    "label": _("Totals scope"),
                    "help_text": _("Calculate the totals row from this page or the entire filtered dataset."),
                },
            ),
            "page_size": (
                forms.TypedChoiceField,
                {
                    **page_size_choices(application_fields),
                    "label": _("Rows per page"),
                    "help_text": _("The number of top-level pivot rows shown per page."),
                },
            ),
        }
        field_definition = field_options.get(name)
        if field_definition is None:
            return super().create_form_field(name, field_info, state)
        field_cls, kwargs = field_definition
        return field_cls(required=False, **kwargs)


def application_field_multiple_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    """Build native multiple-choice options for accessible pivot dimensions."""
    return {"choices": application_field_choices(application_fields)}


def pivot_aggregation_choices(
    _application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": [
            ("count", _("Count")),
            ("sum", _("Sum")),
            ("min", _("Minimum")),
            ("max", _("Maximum")),
            ("avg", _("Average")),
        ],
    }


def pivot_totals_scope_choices(
    _application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": [
            ("page", _("Current page")),
            ("dataset", _("Entire dataset")),
        ],
    }
