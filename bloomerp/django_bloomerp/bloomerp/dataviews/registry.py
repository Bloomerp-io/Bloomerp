from django.utils.translation import gettext_lazy as _

from bloomerp.dataviews.definition import (
    BaseDataview,
    BaseDataviewRenderer,
    DataviewTypeDefinition,
)
from bloomerp.dataviews.calendar.config import CalendarDataView
from bloomerp.dataviews.calendar.renderer import CalendarDataviewRenderer
from bloomerp.dataviews.card.config import CardDataView
from bloomerp.dataviews.card.renderer import CardDataviewRenderer
from bloomerp.dataviews.file_browser.config import FileBrowserDataview
from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer
from bloomerp.dataviews.gant.config import GanttDataView
from bloomerp.dataviews.gant.renderer import GanttDataviewRenderer
from bloomerp.dataviews.kanban.config import KanbanDataView
from bloomerp.dataviews.kanban.renderer import KanbanDataviewRenderer
from bloomerp.dataviews.pivot_table.config import PivotTableDataView
from bloomerp.dataviews.pivot_table.renderer import PivotTableDataviewRenderer
from bloomerp.dataviews.table.config import TableDataView
from bloomerp.dataviews.table.renderer import TableDataviewRenderer
from bloomerp.utils.registry import BaseRegistry


class DataviewRegistry(BaseRegistry[DataviewTypeDefinition]):
    def register(self, key: str, obj: DataviewTypeDefinition) -> None:
        """Register a complete dataview definition under its canonical key."""
        if not isinstance(obj, DataviewTypeDefinition):
            raise TypeError(
                "Dataview definitions must be DataviewTypeDefinition instances."
            )
        if not key or key != obj.key:
            raise ValueError(
                "The registry key must be non-empty and match the dataview definition key."
            )
        if not isinstance(obj.renderer_cls, type) or not issubclass(
            obj.renderer_cls,
            BaseDataviewRenderer,
        ):
            raise TypeError("Dataview renderer_cls must extend BaseDataviewRenderer.")
        if not isinstance(obj.config_cls, type) or not issubclass(
            obj.config_cls,
            BaseDataview,
        ):
            raise TypeError("Dataview config_cls must extend BaseDataview.")

        view_type_field = obj.config_cls.model_fields.get("view_type")
        if view_type_field is None or view_type_field.default != key:
            raise ValueError(
                "The dataview config view_type default must match the definition key."
            )
        unknown_field_options = (
            set(obj.config_cls.application_field_options)
            - set(obj.config_cls.option_field_names())
        )
        if unknown_field_options:
            names = ", ".join(sorted(unknown_field_options))
            raise ValueError(
                f"Dataview application_field_options contains unknown options: {names}."
            )
        invalid_cardinalities = set(
            obj.config_cls.application_field_options.values()
        ) - {"single", "multiple"}
        if invalid_cardinalities:
            names = ", ".join(sorted(invalid_cardinalities))
            raise ValueError(
                "Dataview application_field_options contains unsupported "
                f"cardinalities: {names}."
            )
        super().register(key, obj)

    def choices(self) -> list[tuple[str, str]]:
        """Return model choices from the currently registered dataviews."""
        return [(definition.key, definition.label) for definition in self.values()]


def get_dataview_type_choices() -> list[tuple[str, str]]:
    """Resolve dataview choices when Django evaluates the model field."""
    return DATAVIEW_REGISTRY.choices()


DATAVIEW_REGISTRY = DataviewRegistry(
    registry_item_class=DataviewTypeDefinition
)


def register_dataview(
    definition: DataviewTypeDefinition,
) -> DataviewTypeDefinition:
    """Register and return a dataview definition.

    Third-party Django apps may call this from a top-level ``dataviews`` module;
    Bloomerp imports those modules during application startup.
    """
    DATAVIEW_REGISTRY.register(definition.key, definition)
    return definition


register_dataview(
    DataviewTypeDefinition(
        key="table",
        label=_("Table"),
        description=_("Displays records in a sortable table."),
        icon="fa fa-table",
        renderer_cls=TableDataviewRenderer,
        config_cls=TableDataView,
    )
)

register_dataview(
    DataviewTypeDefinition(
        key="kanban",
        label=_("Kanban"),
        description=_("Displays records in a kanban board."),
        icon="fa fa-columns",
        renderer_cls=KanbanDataviewRenderer,
        config_cls=KanbanDataView,
    )
)

register_dataview(
    DataviewTypeDefinition(
        key="card",
        label=_("Card"),
        description=_("Displays records in a card grid."),
        icon="fa fa-id-card",
        renderer_cls=CardDataviewRenderer,
        config_cls=CardDataView,
    )
)

register_dataview(
    DataviewTypeDefinition(
        key="calendar",
        label=_("Calendar"),
        description=_("Displays records in a calendar view."),
        icon="fa fa-calendar",
        renderer_cls=CalendarDataviewRenderer,
        config_cls=CalendarDataView,
    )
)

register_dataview(
    DataviewTypeDefinition(
        key="gantt",
        label=_("Gantt"),
        description=_("Displays records in a Gantt chart."),
        icon="fa fa-chart-gantt",
        renderer_cls=GanttDataviewRenderer,
        config_cls=GanttDataView,
    )
)

register_dataview(
    DataviewTypeDefinition(
        key="pivot_table",
        label=_("Pivot"),
        description=_("Displays records in a pivot table."),
        icon="fa fa-table",
        renderer_cls=PivotTableDataviewRenderer,
        config_cls=PivotTableDataView,
    )
)

register_dataview(
    DataviewTypeDefinition(
        key="file_browser",
        label=_("File Browser"),
        description=_("File browser"),
        icon="fa fa-file",
        renderer_cls=FileBrowserRenderer,
        config_cls=FileBrowserDataview,
        requires_display_fields=False,
    )
)
