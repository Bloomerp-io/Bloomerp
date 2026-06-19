from enum import Enum
from typing import Any, Callable, Optional

from django.db import models
from django.db.models import Q, QuerySet

from bloomerp.dataviews.base import BaseDataviewRenderer
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.dataviews.calendar import CalendarDataviewRenderer
from bloomerp.dataviews.card import CardDataviewRenderer
from bloomerp.dataviews.gant import GantDataviewRenderer
from bloomerp.dataviews.kanban import KanbanDataviewRenderer
from bloomerp.dataviews.pivot_table import PivotTableDataviewRenderer
from bloomerp.dataviews.table import TableDataviewRenderer
from pydantic import BaseModel, create_model
from dataclasses import dataclass, field
from django import forms


class PageSize(models.IntegerChoices):
    SIZE_10 = 10, '10'
    SIZE_25 = 25, '25'
    SIZE_50 = 50, '50'
    SIZE_100 = 100, '100'


class CalendarViewMode(models.TextChoices):
    DAY = 'day', 'Day'
    WEEK = 'week', 'Week'
    MONTH = 'month', 'Month'


def get_default_display_fields() -> dict:
    """Returns the default display_fields structure for the UserListViewPreference model.

    Returns:
        dict: A dictionary with view types as keys and empty lists as values.
              Structure: {"table": [], "kanban": [], "calendar": []}
              Each list contains ApplicationField IDs in display order.
    """
    return {view_type.value.key: [] for view_type in ViewTypeEnum}


DEFAULT_OPTION_UNSET = object()


def _application_field_choices(
    application_fields: QuerySet[ApplicationField],
    *,
    include_empty: bool = False,
    empty_label: str = "None",
    field_types: set[str] | None = None,
) -> list[tuple[str, str]]:
    choices = [("", empty_label)] if include_empty else []

    for application_field in application_fields:
        if field_types and application_field.field_type not in field_types:
            continue
        choices.append((str(application_field.id), application_field.title))

    return choices


def _application_field_name_choices(
    application_fields: QuerySet[ApplicationField],
    *,
    include_empty: bool = False,
    empty_label: str = "None",
    field_types: set[str] | None = None,
) -> list[tuple[str, str]]:
    choices = [("", empty_label)] if include_empty else []

    for application_field in application_fields:
        if field_types and application_field.field_type not in field_types:
            continue
        choices.append((application_field.field, application_field.title))

    return choices


def _page_size_choices(_application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": PageSize.choices,
        "coerce": int,
    }


def _sort_field_choices(application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": _application_field_name_choices(
            application_fields,
            include_empty=True,
            empty_label="Default",
        ),
        "coerce": lambda value: value or None,
        "empty_value": None,
    }


def _sort_direction_choices(_application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": [
            ("asc", "Ascending"),
            ("desc", "Descending"),
        ]
    }


def _group_by_field_choices(application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": _application_field_choices(
            application_fields,
            include_empty=True,
            empty_label="No grouping",
        ),
        "coerce": int,
        "empty_value": None,
    }


def _date_field_choices(application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": _application_field_choices(
            application_fields,
            include_empty=True,
            empty_label="Select a date field",
            field_types={"DateField", "DateTimeField"},
        ),
        "coerce": int,
        "empty_value": None,
    }


def _view_mode_choices(_application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {"choices": CalendarViewMode.choices}


@dataclass
class PreferenceOption:
    key:str
    label:str
    field_cls:type[forms.Field]
    field_attrs_func:Optional[Callable[[QuerySet[ApplicationField]], dict]] = None
    description:Optional[str] = None
    data_type:type=str
    default_value:Any=DEFAULT_OPTION_UNSET

@dataclass
class ViewTypeDefinition:
    key:str
    label:str
    description:str
    icon:str
    renderer_cls:type[BaseDataviewRenderer]
    opts:list[PreferenceOption] = field(default_factory=list)
    requires_display_fields:bool=True
    model:Optional[type[BaseModel]] = None
    
    def create_opts_form(self, application_fields:QuerySet[ApplicationField]) -> forms.Form:
        """Creates an opts form based on the opts.

        Returns:
            forms.Form: the form
        """
        attrs = {}
        for option in self.opts:
            
            # Get the extra opts
            extra_opts = {}
            if option.field_attrs_func:
                extra_opts = option.field_attrs_func(application_fields)
            
            attrs[option.key] = option.field_cls(
                label=option.label,
                help_text=option.description,
                required=False,
                **extra_opts
            )
            attrs[option.key].widget.attrs.setdefault("class", "select select-sm w-40 bg-base border-0")
        
        return type('OptionsForm', (forms.Form, ), attrs)
    
    def create_model_from_opts(self) -> type[BaseModel]:
        attrs = {}
        for opt in self.opts:
            if opt.default_value is not DEFAULT_OPTION_UNSET:
                model_field = (opt.data_type, opt.default_value)
            else:
                model_field = (opt.data_type, ...)
            
            attrs[opt.key] = model_field
            
        
        model_name = "".join(part.title() for part in self.key.split("_"))
        return create_model(f"{model_name}DataviewOptions", **attrs)
    
    def get_options_model(self) -> type[BaseModel]:
        return self.model or self.create_model_from_opts()
    
class ViewTypeEnum(Enum):
    TABLE = ViewTypeDefinition(
        key="table",
        label="Table",
        description="Displays records in a sortable table.",
        icon="fa fa-table",
        renderer_cls=TableDataviewRenderer,
        opts=[
            PreferenceOption(
                key="page_size",
                label="Page size",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description="The number of records shown on each page.",
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
            PreferenceOption(
                key="sort_field",
                label="Sort on",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_sort_field_choices,
                description="The field used for table sorting.",
                data_type=str | None,
                default_value=None,
            ),
            PreferenceOption(
                key="sort_direction",
                label="Sort direction",
                field_cls=forms.ChoiceField,
                field_attrs_func=_sort_direction_choices,
                description="The direction used for table sorting.",
                data_type=str,
                default_value="asc",
            ),
            # PreferenceOption(
            #     key="group_by_field_id",
            #     label="Grouping",
            #     field_cls=forms.TypedChoiceField,
            #     field_attrs_func=_group_by_field_choices,
            #     description="Optional field used to group table rows.",
            #     data_type=int | None,
            #     default_value=None,
            # ),
        ],
    )
    
    KANBAN = ViewTypeDefinition(
        key="kanban",
        label="Kanban",
        icon="fa fa-table-columns",
        description="Displays records as cards grouped into columns.",
        renderer_cls=KanbanDataviewRenderer,
        opts=[
            PreferenceOption(
                key="group_by_field_id",
                label="Group by",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_group_by_field_choices,
                description="The field used to build Kanban columns.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="page_size",
                label="Cards per column",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description="The number of cards initially shown in each column.",
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
        ],
    )

    CARD = ViewTypeDefinition(
        key="card",
        label="Card",
        icon="fa fa-id-card",
        description="Displays records in a card grid.",
        renderer_cls=CardDataviewRenderer,
        opts=[
            PreferenceOption(
                key="page_size",
                label="Page size",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description="The number of cards shown on each page.",
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
        ],
    )

    CALENDAR = ViewTypeDefinition(
        key="calendar",
        label="Calendar",
        icon="fa fa-calendar",
        description="Displays records on a day, week, or month calendar.",
        renderer_cls=CalendarDataviewRenderer,
        opts=[
            PreferenceOption(
                key="start_field_id",
                label="Date field",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description="The date field used to place records on the calendar.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="end_field_id",
                label="End date field",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description="Optional date field used as the end of an event range.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="view_mode",
                label="View mode",
                field_cls=forms.ChoiceField,
                field_attrs_func=_view_mode_choices,
                description="The calendar period to show.",
                data_type=str,
                default_value=CalendarViewMode.WEEK,
            ),
        ],
    )

    GANT = ViewTypeDefinition(
        key="gant",
        label="Gant",
        icon="fa fa-chart-gantt",
        description="Displays records as a timeline.",
        renderer_cls=GantDataviewRenderer,
        opts=[
            PreferenceOption(
                key="start_field_id",
                label="Start field",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description="The date field used as the start of the timeline item.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="end_field_id",
                label="End field",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description="The date field used as the end of the timeline item.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="group_by_field_id",
                label="Group by",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_group_by_field_choices,
                description="Optional field used to group timeline rows.",
                data_type=int | None,
                default_value=None,
            ),
        ],
    )

    PIVOT_TABLE = ViewTypeDefinition(
        key="pivot_table",
        label="Pivot",
        icon="fa fa-table-cells",
        description="Summarizes records across selected row, column, and value fields.",
        renderer_cls=PivotTableDataviewRenderer,
        opts=[
            PreferenceOption(
                key="row_field_id",
                label="Rows",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_group_by_field_choices,
                description="The field used for pivot rows.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="column_field_id",
                label="Columns",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_group_by_field_choices,
                description="The field used for pivot columns.",
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="value_field_id",
                label="Values",
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_group_by_field_choices,
                description="The field used for pivot values.",
                data_type=int | None,
                default_value=None,
            ),
        ],
    )

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(item.value.key, item.value.label) for item in cls]

    @classmethod
    def values(cls) -> list[str]:
        return [item.value.key for item in cls]

    @classmethod
    def from_key(cls, key: str) -> ViewTypeDefinition:
        for item in cls:
            if item.value.key == key:
                return item.value
        raise ValueError(f"Unsupported dataview type: {key}")

    
class UserListViewPreference(BaseViewPreference):
    """
    Model that stores the preferences of a user for list views for different content types.
    
    Key concepts:
    - Accessible fields: All fields the user has permission to see (based on field-level permissions).
                         These are shown in the display options UI for the user to toggle.
    - Visible fields: The subset of accessible fields that the user has chosen to display
                      for a specific view type. Stored in `display_fields` JSON.
    
    display_fields structure:
    {
        "table": [1, 5, 3],      # ApplicationField IDs in display order
        "kanban": [2, 4],
        "calendar": [1, 2]
    }
    """
    class Meta:
        db_table = 'bloomerp_user_list_view_pref'
        constraints = [
            models.UniqueConstraint(
                fields=["user", "content_type"],
                condition=Q(selected=True),
                name="unique_selected_list_view_preference",
            ),
        ]

    view_type = models.CharField(
        max_length=50,
        choices=ViewTypeEnum.choices(),
        default=ViewTypeEnum.TABLE.value.key,
    )
    split_view_enabled = models.BooleanField(default=False)
    
    # Visible field IDs per view type (list of ApplicationField IDs in order)
    display_fields = models.JSONField(default=get_default_display_fields)
    options : dict = models.JSONField(default=dict)
    default_filters : dict = models.JSONField(default=dict)
    
    @classmethod
    def create_default_for_user(cls, user, content_type_or_model) -> "UserListViewPreference":
        content_type = cls.resolve_content_type(content_type_or_model)
        return cls.objects.create(
            user=user,
            content_type=content_type,
        )

    def get_visible_field_ids(self, view_type: str = None) -> list[int]:
        """Returns the list of ApplicationField IDs that are visible for the given view type.

        Args:
            view_type: The view type to get fields for. Defaults to current view_type.
        Returns:
            list[int]: List of ApplicationField IDs in display order.
        """
        view_type = view_type or self.view_type
        return self.display_fields.get(view_type, [])
    
    def set_visible_field_ids(self, view_type: str, field_ids: list[int]) -> None:
        """Sets the visible field IDs for a specific view type.

        Args:
            view_type: The view type to set fields for.
            field_ids: List of ApplicationField IDs in display order.
        """
        if self.display_fields is None:
            self.display_fields = get_default_display_fields()
        self.display_fields[view_type] = field_ids
    
    def toggle_field(self, view_type: str, field_id: int) -> bool:
        """Toggles a field's visibility for a specific view type.

        Args:
            view_type: The view type to toggle the field for.
            field_id: The ApplicationField ID to toggle.
        Returns:
            bool: True if field is now visible, False if hidden.
        """
        if self.display_fields is None:
            self.display_fields = get_default_display_fields()
        
        current_fields = self.display_fields.get(view_type, [])
        
        if field_id in current_fields:
            current_fields.remove(field_id)
            is_visible = False
        else:
            current_fields.append(field_id)
            is_visible = True
        
        self.display_fields[view_type] = current_fields
        return is_visible
    
    
    
    
