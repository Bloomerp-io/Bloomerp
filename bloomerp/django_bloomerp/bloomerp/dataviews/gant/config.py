from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.base import (
    BaseDataView,
    PageSize,
    PreferenceOption,
    page_size_choices,
)
from bloomerp.dataviews.calendar.config import date_field_choices
from pydantic import Field

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class GanttDataView(BaseDataView):
    """A declarative Gantt dataview."""

    view_type: Literal["gantt"] = "gantt"
    start_field: str
    end_field: str
    dependency_from_field: str | None = None
    dependency_for_field: str | None = None
    page_size: Literal[10, 25, 50, 100] = 25
    display_fields:list = Field(default=list)


def self_relation_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    choices = [("", _("No dependency"))]
    for application_field in application_fields:
        if application_field.field_type not in {"ForeignKey", "OneToOneField"}:
            continue
        if application_field.related_model_id != application_field.content_type_id:
            continue
        choices.append((str(application_field.id), application_field.title))

    return {
        "choices": choices,
        "coerce": int,
        "empty_value": None,
    }


GANTT_OPTIONS = [
    PreferenceOption(
        key="start_field_id",
        label=_("Start field"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=date_field_choices,
        description=_("The date field used as the start of the timeline item."),
        data_type=int | None,
        default_value=None,
        required=True,
    ),
    PreferenceOption(
        key="end_field_id",
        label=_("End field"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=date_field_choices,
        description=_("The date field used as the end of the timeline item."),
        data_type=int | None,
        default_value=None,
        required=True,
    ),
    PreferenceOption(
        key="dependency_from_field_id",
        label=_("Dependency from"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=self_relation_field_choices,
        description=_(
            "Optional self-referencing field whose related record precedes this record."
        ),
        data_type=int | None,
        default_value=None,
    ),
    PreferenceOption(
        key="dependency_for_field_id",
        label=_("Dependency for"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=self_relation_field_choices,
        description=_(
            "Optional self-referencing field whose related record follows this record."
        ),
        data_type=int | None,
        default_value=None,
    ),
    PreferenceOption(
        key="page_size",
        label=_("Rows per page"),
        field_cls=forms.TypedChoiceField,
        field_attrs_func=page_size_choices,
        description=_("The number of timeline rows loaded at a time."),
        data_type=int,
        default_value=PageSize.SIZE_25,
    ),
]
