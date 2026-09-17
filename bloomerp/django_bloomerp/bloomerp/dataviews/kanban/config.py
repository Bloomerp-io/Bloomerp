from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataView,
    PageSize,
    PreferenceOption,
    application_field_choices,
    page_size_choices,
)
from bloomerp.dataviews.table.config import (
    sort_direction_choices,
    sort_field_choices,
)

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class KanbanDataView(BaseDataView):
    """A declarative Kanban dataview."""

    view_type: Literal["kanban"] = "kanban"
    group_by_field: str | None = None
    page_size: Literal[10, 25, 50, 100] = 25
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "asc"


def group_by_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("No grouping"),
        ),
        "coerce": int,
        "empty_value": None,
    }


KANBAN_OPTIONS = [
    PreferenceOption(
        key="group_by_field_id",
        label=_("Group by"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=group_by_field_choices,
        description=_("The field used to build Kanban columns."),
        data_type=int | None,
        default_value=None,
    ),
    PreferenceOption(
        key="page_size",
        label=_("Cards per column"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=page_size_choices,
        description=_("The number of cards initially shown in each column."),
        data_type=int,
        default_value=PageSize.SIZE_25,
    ),
    PreferenceOption(
        key="sort_field",
        label=_("Sort on"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=sort_field_choices,
        description=_("The field used for table sorting."),
        data_type=str | None,
        default_value=None,
    ),
    PreferenceOption(
        key="sort_direction",
        label=_("Sort direction"),
        field_cls=forms.ChoiceField,
        field_attrs_func=sort_direction_choices,
        description=_("The direction used for table sorting."),
        data_type=str,
        default_value="asc",
    ),
]
