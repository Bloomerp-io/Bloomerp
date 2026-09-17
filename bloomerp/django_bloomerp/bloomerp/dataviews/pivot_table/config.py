from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field, model_validator

from bloomerp.dataviews.definition import (
    BaseDataView,
    PageSize,
    PreferenceOption,
    application_field_choices,
    page_size_choices,
)

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class PivotTableDataView(BaseDataView):
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


class PivotTableDataviewOptions(BaseModel):
    """Validated persisted options for the pivot-table renderer."""

    row_field_ids: list[int] = Field(default_factory=list)
    column_field_ids: list[int] = Field(default_factory=list)
    value_field_ids: list[int] = Field(default_factory=list)
    aggregation: str = "count"
    show_row_totals: bool = True
    show_column_totals: bool = True
    totals_scope: str = "page"
    page_size: int = PageSize.SIZE_25

    @model_validator(mode="before")
    @classmethod
    def migrate_single_value_field(cls, data: Any) -> Any:
        """Preserve pivot preferences saved before values became multi-select."""
        if not isinstance(data, dict) or data.get("value_field_ids"):
            return data

        value_field_id = data.get("value_field_id")
        if value_field_id in (None, ""):
            return data

        migrated = dict(data)
        migrated["value_field_ids"] = [value_field_id]
        return migrated


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


PIVOT_TABLE_OPTIONS = [
    PreferenceOption(
        key="row_field_ids",
        label=_("Rows"),
        field_cls=forms.MultipleChoiceField,
        field_attrs_func=application_field_multiple_choices,
        description=_("Fields used to build the expandable row hierarchy."),
        data_type=list[int],
        default_value=[],
    ),
    PreferenceOption(
        key="column_field_ids",
        label=_("Columns"),
        field_cls=forms.MultipleChoiceField,
        field_attrs_func=application_field_multiple_choices,
        description=_("Fields used to build nested column headers."),
        data_type=list[int],
        default_value=[],
    ),
    PreferenceOption(
        key="value_field_ids",
        label=_("Values"),
        field_cls=forms.MultipleChoiceField,
        field_attrs_func=application_field_multiple_choices,
        description=_("Fields aggregated into the leaf columns of the pivot table."),
        data_type=list[int],
        default_value=[],
    ),
    PreferenceOption(
        key="aggregation",
        label=_("Aggregation"),
        field_cls=forms.ChoiceField,
        field_attrs_func=pivot_aggregation_choices,
        description=_(
            "Numeric fields support all aggregations; booleans support sum and count; other fields use count."
        ),
        data_type=str,
        default_value="count",
    ),
    PreferenceOption(
        key="show_row_totals",
        label=_("Show row totals"),
        field_cls=forms.BooleanField,
        description=_("Add a total column for each row."),
        data_type=bool,
        default_value=True,
    ),
    PreferenceOption(
        key="show_column_totals",
        label=_("Show column totals"),
        field_cls=forms.BooleanField,
        description=_("Add a totals row beneath the pivot table."),
        data_type=bool,
        default_value=True,
    ),
    PreferenceOption(
        key="totals_scope",
        label=_("Totals scope"),
        field_cls=forms.ChoiceField,
        field_attrs_func=pivot_totals_scope_choices,
        description=_(
            "Calculate the totals row from this page or the entire filtered dataset."
        ),
        data_type=str,
        default_value="page",
    ),
    PreferenceOption(
        key="page_size",
        label=_("Rows per page"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=page_size_choices,
        description=_("The number of top-level pivot rows shown per page."),
        data_type=int,
        default_value=PageSize.SIZE_25,
    ),
]
