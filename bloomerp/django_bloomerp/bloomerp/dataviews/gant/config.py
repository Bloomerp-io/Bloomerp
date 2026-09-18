from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataview,
    page_size_choices,
)
from bloomerp.dataviews.calendar.config import date_field_choices
from pydantic import Field

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
    display_fields: list = Field(default_factory=list)

    @classmethod
    def create_form_field(cls, name, field_info, state):
        application_fields = state.accessible_fields
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
