from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataview,
    application_field_choices,
    page_size_choices,
)
from bloomerp.dataviews.table.config import (
    sort_direction_choices,
    sort_field_choices,
)
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class KanbanDataView(BaseDataview):
    """A declarative Kanban dataview."""

    view_type: Literal["kanban"] = "kanban"
    group_by_field: str | None = None
    page_size: Literal[10, 25, 50, 100] = 25
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "asc"
    application_field_options = {
        "group_by_field": "single",
        "sort_field": "single",
    }

    @classmethod
    def create_form_field(cls, name, field_info, state):
        application_fields = state.accessible_fields
        field_options = {
            "group_by_field": (
                forms.TypedChoiceField,
                {
                    **group_by_field_choices(application_fields),
                    "label": _("Group by"),
                    "help_text": _("The field used to build Kanban columns."),
                },
            ),
            "page_size": (
                forms.TypedChoiceField,
                {
                    **page_size_choices(application_fields),
                    "label": _("Cards per column"),
                    "help_text": _("The number of cards initially shown in each column."),
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


def group_by_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("No grouping"),
        ),
        "coerce": lambda value: value or None,
        "empty_value": None,
    }
