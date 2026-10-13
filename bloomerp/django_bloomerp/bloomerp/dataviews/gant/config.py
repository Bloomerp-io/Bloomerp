from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from pydantic import Field

from bloomerp.dataviews.calendar.config import date_field_choices
from bloomerp.dataviews.definition import (
    BaseDataview,
    page_size_choices,
)
from bloomerp.dataviews.table.config import sort_direction_choices, sort_field_choices
from bloomerp.dataviews.table.renderer import TableDataviewRenderer

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class GanttDataView(BaseDataview):
    """A declarative Gantt dataview."""

    view_type: Literal["gantt"] = "gantt"
    start_field: str
    end_field: str
    dependency_from_field: str | None = None
    dependency_for_field: str | None = None
    page_size: Literal[10, 25, 50, 100] = 25
    ordering: str | None = None
    ordering_direction: Literal["asc", "desc"] = "asc"
    display_fields: list = Field(default_factory=list)
    application_field_options = {
        "start_field": "single",
        "end_field": "single",
        "dependency_from_field": "single",
        "dependency_for_field": "single",
        "ordering": "single",
    }

    @classmethod
    def create_form_field(cls, name: str, field_info: Any, state: Any) -> forms.Field:
        """Build a Gantt option field using the shared sorting choices where appropriate."""
        application_fields = state.accessible_fields
        ordering_options = sort_field_choices(application_fields)
        eligible_ordering_fields = TableDataviewRenderer._get_sortable_fields_by_name(
            state.queryset, state.fields,
        )
        ordering_options["choices"] = [
            (value, label)
            for value, label in ordering_options["choices"]
            if not value or value in eligible_ordering_fields
        ]
        field_options = {
            "start_field": (
                forms.TypedChoiceField,
                {
                    **date_field_choices(application_fields),
                    "label": _("Start field"),
                    "help_text": _("The date field used as the start of the timeline item."),
                    "required": True,
                },
            ),
            "end_field": (
                forms.TypedChoiceField,
                {
                    **date_field_choices(application_fields),
                    "label": _("End field"),
                    "help_text": _("The date field used as the end of the timeline item."),
                    "required": True,
                },
            ),
            "dependency_from_field": (
                forms.TypedChoiceField,
                {
                    **self_relation_field_choices(application_fields),
                    "label": _("Dependency from"),
                    "help_text": _("Optional self-referencing field whose related record precedes this record."),
                    "required": False,
                },
            ),
            "dependency_for_field": (
                forms.TypedChoiceField,
                {
                    **self_relation_field_choices(application_fields),
                    "label": _("Dependency for"),
                    "help_text": _("Optional self-referencing field whose related record follows this record."),
                    "required": False,
                },
            ),
            "page_size": (
                forms.TypedChoiceField,
                {
                    **page_size_choices(application_fields),
                    "label": _("Rows per page"),
                    "help_text": _("The number of timeline rows loaded at a time."),
                    "required": False,
                },
            ),
            "ordering": (
                forms.TypedChoiceField,
                {
                    **ordering_options,
                    "label": _("Order by"),
                    "help_text": _("The field used to order timeline records."),
                    "required": False,
                },
            ),
            "ordering_direction": (
                forms.ChoiceField,
                {
                    **sort_direction_choices(application_fields),
                    "label": _("Order direction"),
                    "required": False,
                },
            ),
        }
        field_definition = field_options.get(name)
        if field_definition is None:
            return super().create_form_field(name, field_info, state)
        field_cls, kwargs = field_definition
        return field_cls(**kwargs)


def self_relation_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    choices = [("", _("No dependency"))]
    for application_field in application_fields:
        if application_field.field_type not in {"ForeignKey", "OneToOneField"}:
            continue
        if application_field.related_model_id != application_field.content_type_id:
            continue
        choices.append((application_field.field, application_field.title))

    return {
        "choices": choices,
        "coerce": lambda value: value or None,
        "empty_value": None,
    }
