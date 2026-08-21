from django.utils.translation import gettext_lazy as _
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import Q, QuerySet

from bloomerp.dataviews.base import BaseDataviewRenderer
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    BaseDataView,
    CalendarDataView,
    CardDataView,
    GanttDataView,
    KanbanDataView,
    PivotTableDataView,
    TableDataView,
    get_model_config,
)
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.dataviews.calendar import CalendarDataviewRenderer
from bloomerp.dataviews.card import CardDataviewRenderer
from bloomerp.dataviews.gant import GantDataviewRenderer
from bloomerp.dataviews.kanban import KanbanDataviewRenderer
from bloomerp.dataviews.pivot_table import PivotTableDataviewRenderer
from bloomerp.dataviews.table import TableDataviewRenderer
from pydantic import BaseModel, create_model, model_validator
from dataclasses import dataclass, field
from django import forms
from pydantic import Field as PydanticField

if TYPE_CHECKING:
    from bloomerp.models.users.user import AbstractBloomerpUser

class PageSize(models.IntegerChoices):
    SIZE_10 = 10, _('10')
    SIZE_25 = 25, _('25')
    SIZE_50 = 50, _('50')
    SIZE_100 = 100, _('100')


class CalendarViewMode(models.TextChoices):
    DAY = 'day', _('Day')
    WEEK = 'week', _('Week')
    MONTH = 'month', _('Month')
    YEAR = 'year', _('Year')
    LIST = 'list', _('List')


def get_default_display_fields() -> dict:
    """Returns the default display_fields structure for the UserListViewPreference model.

    Returns:
        dict: A dictionary with view types as keys and empty lists as values.
              Structure: {"table": [], "kanban": [], "calendar": []}
              Each list contains ApplicationField IDs in display order.
    """
    return {view_type.value.key: [] for view_type in DataviewType}


DEFAULT_OPTION_UNSET = object()


def _application_field_choices(
    application_fields: QuerySet[ApplicationField],
    *,
    include_empty: bool = False,
    empty_label: str = _("None"),
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
    empty_label: str = _("None"),
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
            empty_label=_("Default"),
        ),
        "coerce": lambda value: value or None,
        "empty_value": None,
    }


def _sort_direction_choices(_application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": [
            ("asc", _("Ascending")),
            ("desc", _("Descending")),
        ]
    }


def _group_by_field_choices(application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": _application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("No grouping"),
        ),
        "coerce": int,
        "empty_value": None,
    }


def _application_field_multiple_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    """Build native multiple-choice options for accessible pivot dimensions."""
    return {
        "choices": _application_field_choices(application_fields),
    }


def _pivot_aggregation_choices(
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


def _pivot_totals_scope_choices(
    _application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": [
            ("page", _("Current page")),
            ("dataset", _("Entire dataset")),
        ],
    }


def _date_field_choices(application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {
        "choices": _application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("Select a date field"),
            field_types={"DateField", "DateTimeField"},
        ),
        "coerce": int,
        "empty_value": None,
    }


def _self_relation_field_choices(application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
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


def _view_mode_choices(_application_fields: QuerySet[ApplicationField]) -> dict[str, Any]:
    return {"choices": CalendarViewMode.choices}


def _calendar_color_field_choices(
    application_fields: QuerySet[ApplicationField],
) -> dict[str, Any]:
    return {
        "choices": _application_field_choices(
            application_fields,
            include_empty=True,
            empty_label=_("No color grouping"),
        ),
        "coerce": int,
        "empty_value": None,
    }


@dataclass
class PreferenceOption:
    key:str
    label:str
    field_cls:type[forms.Field]
    field_attrs_func:Optional[Callable[[QuerySet[ApplicationField]], dict]] = None
    description:Optional[str] = None
    data_type:type=str
    default_value:Any=DEFAULT_OPTION_UNSET
    required:bool=False

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
                required=option.required,
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


class PivotTableDataviewOptions(BaseModel):
    """Validated persisted options for the pivot-table renderer."""

    row_field_ids: list[int] = PydanticField(default_factory=list)
    column_field_ids: list[int] = PydanticField(default_factory=list)
    value_field_ids: list[int] = PydanticField(default_factory=list)
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


class DataviewType(Enum):
    TABLE = ViewTypeDefinition(
        key="table",
        label=_("Table"),
        description=_("Displays records in a sortable table."),
        icon="fa fa-table",
        renderer_cls=TableDataviewRenderer,
        opts=[
            PreferenceOption(
                key="page_size",
                label=_("Page size"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description=_("The number of records shown on each page."),
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
            PreferenceOption(
                key="sort_field",
                label=_("Sort on"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_sort_field_choices,
                description=_("The field used for table sorting."),
                data_type=str | None,
                default_value=None,
            ),
            PreferenceOption(
                key="sort_direction",
                label=_("Sort direction"),
                field_cls=forms.ChoiceField,
                field_attrs_func=_sort_direction_choices,
                description=_("The direction used for table sorting."),
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
        label=_("Kanban"),
        icon="fa fa-table-columns",
        description=_("Displays records as cards grouped into columns."),
        renderer_cls=KanbanDataviewRenderer,
        opts=[
            PreferenceOption(
                key="group_by_field_id",
                label=_("Group by"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_group_by_field_choices,
                description=_("The field used to build Kanban columns."),
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="page_size",
                label=_("Cards per column"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description=_("The number of cards initially shown in each column."),
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
            PreferenceOption(
                key="sort_field",
                label=_("Sort on"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_sort_field_choices,
                description=_("The field used for table sorting."),
                data_type=str | None,
                default_value=None,
            ),
            PreferenceOption(
                key="sort_direction",
                label=_("Sort direction"),
                field_cls=forms.ChoiceField,
                field_attrs_func=_sort_direction_choices,
                description=_("The direction used for table sorting."),
                data_type=str,
                default_value="asc",
            ),
        ],
    )

    CARD = ViewTypeDefinition(
        key="card",
        label=_("Card"),
        icon="fa fa-id-card",
        description=_("Displays records in a card grid."),
        renderer_cls=CardDataviewRenderer,
        opts=[
            PreferenceOption(
                key="page_size",
                label=_("Page size"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description=_("The number of cards shown on each page."),
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
        ],
    )

    CALENDAR = ViewTypeDefinition(
        key="calendar",
        label=_("Calendar"),
        icon="fa fa-calendar",
        description=_("Displays records on a day, week, month, year, or list calendar."),
        renderer_cls=CalendarDataviewRenderer,
        opts=[
            PreferenceOption(
                key="start_field_id",
                label=_("Date field"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description=_("The date field used to place records on the calendar."),
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="end_field_id",
                label=_("End date field"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description=_("Optional date field used as the end of an event range."),
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="view_mode",
                label=_("View mode"),
                field_cls=forms.ChoiceField,
                field_attrs_func=_view_mode_choices,
                description=_("The calendar period to show."),
                data_type=str,
                default_value=CalendarViewMode.WEEK,
            ),
            PreferenceOption(
                key="color_grouping_field_id",
                label=_("Color grouping"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_calendar_color_field_choices,
                description=_("Optional field used to color calendar items and build the legend."),
                data_type=int | None,
                default_value=None,
            ),
        ],
    )

    GANT = ViewTypeDefinition(
        key="gant",
        label=_("Gantt"),
        icon="fa fa-chart-gantt",
        description=_("Displays records as a timeline."),
        renderer_cls=GantDataviewRenderer,
        opts=[
            PreferenceOption(
                key="start_field_id",
                label=_("Start field"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description=_("The date field used as the start of the timeline item."),
                data_type=int | None,
                default_value=None,
                required=True,
            ),
            PreferenceOption(
                key="end_field_id",
                label=_("End field"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_date_field_choices,
                description=_("The date field used as the end of the timeline item."),
                data_type=int | None,
                default_value=None,
                required=True,
            ),
            PreferenceOption(
                key="dependency_from_field_id",
                label=_("Dependency from"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_self_relation_field_choices,
                description=_("Optional self-referencing field whose related record precedes this record."),
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="dependency_for_field_id",
                label=_("Dependency for"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_self_relation_field_choices,
                description=_("Optional self-referencing field whose related record follows this record."),
                data_type=int | None,
                default_value=None,
            ),
            PreferenceOption(
                key="page_size",
                label=_("Rows per page"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description=_("The number of timeline rows loaded at a time."),
                data_type=int,
                default_value=PageSize.SIZE_25,
            ),
        ],
    )

    PIVOT_TABLE = ViewTypeDefinition(
        key="pivot_table",
        label=_("Pivot"),
        icon="fa fa-table-cells",
        description=_("Summarizes records across selected row, column, and value fields."),
        renderer_cls=PivotTableDataviewRenderer,
        requires_display_fields=False,
        model=PivotTableDataviewOptions,
        opts=[
            PreferenceOption(
                key="row_field_ids",
                label=_("Rows"),
                field_cls=forms.MultipleChoiceField,
                field_attrs_func=_application_field_multiple_choices,
                description=_("Fields used to build the expandable row hierarchy."),
                data_type=list[int],
                default_value=[],
            ),
            PreferenceOption(
                key="column_field_ids",
                label=_("Columns"),
                field_cls=forms.MultipleChoiceField,
                field_attrs_func=_application_field_multiple_choices,
                description=_("Fields used to build nested column headers."),
                data_type=list[int],
                default_value=[],
            ),
            PreferenceOption(
                key="value_field_ids",
                label=_("Values"),
                field_cls=forms.MultipleChoiceField,
                field_attrs_func=_application_field_multiple_choices,
                description=_("Fields aggregated into the leaf columns of the pivot table."),
                data_type=list[int],
                default_value=[],
            ),
            PreferenceOption(
                key="aggregation",
                label=_("Aggregation"),
                field_cls=forms.ChoiceField,
                field_attrs_func=_pivot_aggregation_choices,
                description=_("Numeric fields support all aggregations; booleans support sum and count; other fields use count."),
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
                field_attrs_func=_pivot_totals_scope_choices,
                description=_("Calculate the totals row from this page or the entire filtered dataset."),
                data_type=str,
                default_value="page",
            ),
            PreferenceOption(
                key="page_size",
                label=_("Rows per page"),
                field_cls=forms.TypedChoiceField,
                field_attrs_func=_page_size_choices,
                description=_("The number of top-level pivot rows shown per page."),
                data_type=int,
                default_value=PageSize.SIZE_25,
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
        verbose_name = _("User List View Preference")
        verbose_name_plural = _("User List View Preferences")
        db_table = 'bloomerp_user_list_view_pref'
        constraints = [
            models.UniqueConstraint(
                fields=["user", "content_type"],
                condition=Q(selected=True),
                name="unique_selected_list_view_preference",
            ),
            models.UniqueConstraint(
                fields=["user", "source_object"],
                condition=Q(source_object__isnull=False),
                name="unique_list_view_preference_reference",
            ),
        ]

    view_type = models.CharField(
        max_length=50,
        choices=DataviewType.choices(),
        default=DataviewType.TABLE.value.key,
        verbose_name=_("View Type"),
    )
    split_view_enabled = models.BooleanField(default=False, verbose_name=_("Split View Enabled"))
    
    # Visible field IDs per view type (list of ApplicationField IDs in order)
    display_fields = models.JSONField(default=get_default_display_fields, verbose_name=_("Display Fields"))
    options : dict = models.JSONField(default=dict, verbose_name=_("Options"))
    default_filters : dict = models.JSONField(default=dict, verbose_name=_("Default Filters"))
    
    @classmethod
    def create_default_for_user(cls, user, **scope) -> "UserListViewPreference":
        """Create the user's default list-view preference for a content type.

        Expected scope: ``content_type_id``.
        """
        content_type = ContentType.objects.get(pk=scope["content_type_id"])
        model = content_type.model_class()
        config = get_model_config(model) if model is not None else None
        default_dataviews = (
            config.model_view_settings.default_dataviews
            if config is not None and config.model_view_settings is not None
            else []
        )

        if default_dataviews:
            return cls._create_configured_defaults(
                user=user,
                content_type=content_type,
                default_dataviews=default_dataviews,
            )

        return cls.objects.create(
            user=user,
            content_type=content_type,
        )

    @classmethod
    def _create_configured_defaults(
        cls,
        *,
        user: "AbstractBloomerpUser",
        content_type: ContentType,
        default_dataviews: list[BaseDataView],
    ) -> "UserListViewPreference":
        """Materialize all configured data views and return the selected one."""
        from bloomerp.services.permission_services import (
            UserPermissionManager,
            create_permission_str,
        )

        model = content_type.model_class()
        application_fields = list(
            ApplicationField.objects.filter(content_type=content_type)
        )
        fields_by_name = {
            application_field.field: application_field
            for application_field in application_fields
        }
        accessible_field_ids = set(
            UserPermissionManager(user).get_accessible_fields(
                content_type,
                create_permission_str(model, "view"),
            ).values_list("id", flat=True)
        )

        selected_preference: UserListViewPreference | None = None
        with transaction.atomic():
            for data_view in default_dataviews:
                display_fields = get_default_display_fields()
                display_fields[data_view.view_type] = cls._resolve_field_ids(
                    data_view.display_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                )
                options = {
                    data_view.view_type: cls._resolve_data_view_options(
                        data_view,
                        fields_by_name=fields_by_name,
                        accessible_field_ids=accessible_field_ids,
                    )
                }
                default_filters = cls._resolve_default_filters(
                    data_view.default_filters,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                )

                preference = cls.objects.create(
                    user=user,
                    content_type=content_type,
                    name=data_view.name,
                    selected=data_view.is_default,
                    view_type=data_view.view_type,
                    split_view_enabled=data_view.split_view_enabled,
                    display_fields=display_fields,
                    options=options,
                    default_filters=default_filters,
                )
                if data_view.is_default:
                    selected_preference = preference

        if selected_preference is None:
            raise ValueError("Configured data views must define one default.")
        return selected_preference

    @staticmethod
    def _resolve_field(
        field_name: str | None,
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> ApplicationField | None:
        """Resolve a declared field name without granting inaccessible fields."""
        if field_name is None:
            return None

        normalized_name = field_name.strip()
        application_field = fields_by_name.get(normalized_name)
        if application_field is None:
            raise ValueError(f"Unknown data view field '{normalized_name}'.")
        if application_field.id not in accessible_field_ids:
            return None
        return application_field

    @classmethod
    def _resolve_field_ids(
        cls,
        field_names: list[str],
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> list[int]:
        """Resolve declared field names to accessible ApplicationField IDs."""
        resolved_ids: list[int] = []
        for field_name in field_names:
            application_field = cls._resolve_field(
                field_name,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            if application_field is not None:
                resolved_ids.append(application_field.id)
        return resolved_ids

    @classmethod
    def _resolve_data_view_options(
        cls,
        data_view: BaseDataView,
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> dict[str, Any]:
        """Translate developer-facing field names to persisted view options."""
        def field_id(field_name: str | None) -> int | None:
            application_field = cls._resolve_field(
                field_name,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            return application_field.id if application_field is not None else None

        def field_name(field: str | None) -> str | None:
            application_field = cls._resolve_field(
                field,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            return application_field.field if application_field is not None else None

        if isinstance(data_view, TableDataView):
            return {
                "page_size": data_view.page_size,
                "sort_field": field_name(data_view.sort_field),
                "sort_direction": data_view.sort_direction,
            }
        if isinstance(data_view, KanbanDataView):
            return {
                "group_by_field_id": field_id(data_view.group_by_field),
                "page_size": data_view.page_size,
                "sort_field": field_name(data_view.sort_field),
                "sort_direction": data_view.sort_direction,
            }
        if isinstance(data_view, CardDataView):
            return {"page_size": data_view.page_size}
        if isinstance(data_view, CalendarDataView):
            return {
                "start_field_id": field_id(data_view.start_field),
                "end_field_id": field_id(data_view.end_field),
                "view_mode": data_view.view_mode,
                "color_grouping_field_id": field_id(
                    data_view.color_grouping_field
                ),
            }
        if isinstance(data_view, GanttDataView):
            return {
                "start_field_id": field_id(data_view.start_field),
                "end_field_id": field_id(data_view.end_field),
                "dependency_from_field_id": field_id(
                    data_view.dependency_from_field
                ),
                "dependency_for_field_id": field_id(
                    data_view.dependency_for_field
                ),
                "page_size": data_view.page_size,
            }
        if isinstance(data_view, PivotTableDataView):
            return {
                "row_field_ids": cls._resolve_field_ids(
                    data_view.row_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                ),
                "column_field_ids": cls._resolve_field_ids(
                    data_view.column_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                ),
                "value_field_ids": cls._resolve_field_ids(
                    data_view.value_fields,
                    fields_by_name=fields_by_name,
                    accessible_field_ids=accessible_field_ids,
                ),
                "aggregation": data_view.aggregation,
                "show_row_totals": data_view.show_row_totals,
                "show_column_totals": data_view.show_column_totals,
                "totals_scope": data_view.totals_scope,
                "page_size": data_view.page_size,
            }
        raise ValueError(f"Unsupported default data view '{data_view.view_type}'.")

    @classmethod
    def _resolve_default_filters(
        cls,
        default_filters: dict[str, str | list[str]],
        *,
        fields_by_name: dict[str, ApplicationField],
        accessible_field_ids: set[int],
    ) -> dict[str, str | list[str]]:
        """Keep configured filters only when their root field is accessible."""
        resolved_filters: dict[str, str | list[str]] = {}
        for filter_key, value in default_filters.items():
            root_field_name = filter_key.split("__", 1)[0]
            application_field = cls._resolve_field(
                root_field_name,
                fields_by_name=fields_by_name,
                accessible_field_ids=accessible_field_ids,
            )
            if application_field is not None:
                resolved_filters[filter_key] = value
        return resolved_filters

    @classmethod
    def copy_preference_for_user(
        cls,
        *,
        user,
        source: "UserListViewPreference",
        name: str,
        scope: dict | None = None,
    ) -> "UserListViewPreference":
        """Copy a list-view preference and its serialized options."""
        return cls._create_preference_copy(
            user=user,
            source=source,
            name=name,
            scope=scope,
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
    
    @property
    def should_display_field_options(self) -> bool:
        """Determines if field visibility options should be displayed for the current view type.

        Returns:
            bool: True if field visibility options should be shown, False otherwise.
        """
        view_type_def = DataviewType.from_key(self.view_type)
        return view_type_def.requires_display_fields
    
    
