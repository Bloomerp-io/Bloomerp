from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from django import forms
from django.db.models import ForeignKey, OneToOneField, QuerySet
from django.utils.translation import gettext_lazy as _
from pydantic import Field, field_validator
from pydantic.fields import FieldInfo

from bloomerp.dataviews.definition import (
    BaseDataview,
    DataviewState,
    application_field_choices,
    page_size_choices,
)
from bloomerp.dataviews.table.config import (
    sort_direction_choices,
    sort_field_choices,
)
from bloomerp.form_fields.mapping_field import MappingField

if TYPE_CHECKING:
    from bloomerp.models.application_field import ApplicationField


class KanbanOptionsForm(forms.Form):
    """Keep editable lane rows aligned with their separately persisted order."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Restore the mapping editor in explicit lane order after a database reload."""
        super().__init__(*args, **kwargs)
        groups = self.initial.get("custom_groupings", {})
        order = self.initial.get("custom_group_order", [])
        if isinstance(groups, dict):
            ordered = {label: groups[label] for label in order if label in groups}
            ordered.update(groups)
            self.initial["custom_groupings"] = ordered

    def clean(self) -> dict[str, Any]:
        """Derive lane order from validated submitted rows rather than JSON object keys."""
        cleaned = super().clean()
        if "custom_groupings" in cleaned:
            cleaned["custom_group_order"] = list(cleaned["custom_groupings"])
        return cleaned


class KanbanDataView(BaseDataview):
    """A declarative Kanban dataview."""

    view_type: Literal["kanban"] = "kanban"
    group_by_field: str | None = None
    custom_groupings: dict[str, list[str]] = Field(default_factory=dict)
    custom_group_order: list[str] = Field(default_factory=list)
    lane_colouring: dict[str, str] = Field(default_factory=dict)
    page_size: Literal[10, 25, 50, 100] = 25
    sort_field: str | None = None
    sort_direction: Literal["asc", "desc"] = "asc"
    application_field_options = {
        "group_by_field": "single",
        "sort_field": "single",
    }

    @classmethod
    def form_factory(cls, state: DataviewState) -> type[forms.Form]:
        """Apply lane-order restoration and cleaning to the generated options form."""
        return type("KanbanOrderedOptionsForm", (KanbanOptionsForm, super().form_factory(state)), {})

    @classmethod
    def _mapping_lane_metadata(cls, state: DataviewState) -> list[dict[str, Any]]:
        """Reuse one permission-filtered metadata query across both mapping editors."""
        from .renderer import KanbanDataviewRenderer

        cache_key = "_kanban_mapping_lane_metadata"
        if cache_key not in state.context:
            grouping = KanbanDataviewRenderer.get_group_by_field(
                state.fields, state.options
            )
            related_queryset = None
            if grouping and isinstance(
                grouping._get_model_field(), (ForeignKey, OneToOneField)
            ):
                related_queryset = KanbanDataviewRenderer.get_allowed_related_queryset(
                    grouping, state.request.user
                )
                if KanbanDataviewRenderer.has_too_many_related_columns(
                    related_queryset
                ):
                    grouping = None
            state.context[cache_key] = (
                KanbanDataviewRenderer.build_lane_metadata(
                    state.queryset,
                    grouping,
                    state.request.user,
                    related_queryset,
                )
                if grouping
                else []
            )
        return state.context[cache_key]

    @classmethod
    def create_form_field(
        cls, name: str, field_info: FieldInfo, state: DataviewState
    ) -> forms.Field:
        """Build typed mapping editors from the currently accessible grouping values."""
        if name == "custom_group_order":
            return forms.JSONField(required=False, widget=forms.HiddenInput())
        if name in {"custom_groupings", "lane_colouring"}:
            from .renderer import KanbanDataviewRenderer

            groups = cls._mapping_lane_metadata(state)
            choices = [(group["request_value"], group["label"]) for group in groups]
            if name == "custom_groupings":
                known_values = {key for key, _label in choices}
                choices.extend(
                    (value, value)
                    for values in getattr(
                        state.options, "custom_groupings", {}
                    ).values()
                    for value in values
                    if value not in known_values
                )
                return MappingField(
                    right_field=forms.MultipleChoiceField(choices=choices),
                    required=False,
                    label=_("Custom groups"),
                    help_text=_(
                        "Name each lane and select its values. Unmapped values keep their own lanes."
                    ),
                )
            coloured_groups = KanbanDataviewRenderer.merge_lane_metadata(
                groups,
                getattr(state.options, "custom_groupings", {}),
                getattr(state.options, "custom_group_order", []),
            )
            choices = [
                (group.get("colour_key", group["request_value"]), group["label"])
                for group in coloured_groups
            ]
            known = {key for key, _label in choices}
            choices.extend(
                (key, key)
                for key in getattr(state.options, "lane_colouring", {})
                if key not in known
            )
            return MappingField(
                left_field=forms.CharField(
                    widget=forms.Select(choices=[("", _("Choose lane")), *choices])
                ),
                right_field=forms.RegexField(
                    regex=r"^#[0-9a-fA-F]{6}$",
                    widget=forms.TextInput(attrs={"type": "color"}),
                ),
                required=False,
                label=_("Lane colours"),
                help_text=_(
                    "Map custom lane names or original values to six-digit hex colours. Unused colours are ignored."
                ),
            )
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
                    "help_text": _(
                        "The number of cards initially shown in each column."
                    ),
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

    @field_validator("custom_groupings")
    @classmethod
    def validate_groupings(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        """Require named, nonempty, disjoint custom lanes."""
        seen: set[str] = set()
        for label, members in value.items():
            if not label.strip() or not members:
                raise ValueError("Custom groups need a name and at least one value.")
            if len(members) != len(set(members)) or seen.intersection(members):
                raise ValueError("Each value can belong to only one custom group.")
            seen.update(members)
        return value

    @field_validator("lane_colouring")
    @classmethod
    def validate_colours(cls, value: dict[str, str]) -> dict[str, str]:
        """Accept only safe CSS hex colours for persisted lane styles."""
        if any(
            not re.fullmatch(r"#[0-9a-fA-F]{6}", colour) for colour in value.values()
        ):
            raise ValueError(
                "Lane colours must use six-digit hex colours, such as #336699."
            )
        return value


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
